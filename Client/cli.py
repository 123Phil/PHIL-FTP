""" Simplified FTP client
Author: Phillip Stewart


"""


import os
import sys
import socket
import struct


_SOCK = None
_HOST = 'localhost'
_PORT = 20
_USAGE = "  Usage: python3 cli.py <HOST> <PORT #>"
_USAGE2 = """Valid commands are:
  ls
  get <filename>
  put <filename>
  quit"""
_PROMPT = 'ftp> '


def _log(msg):
	sys.stdout.write(msg + '\n')
	sys.stdout.flush()

def _err_log(msg):
	sys.stderr.write(msg + '\n')
	sys.stderr.flush()


def check_args(args):
	global _HOST, _PORT
	if len(args) != 3:
		_log(_USAGE)
		sys.exit(0)
	_HOST = args[1]
	try:
		_PORT = int(args[2])
	except ValueError as e:
		_err_log("Invalid port number supplied\n" + _USAGE)
		sys.exit(1)


def get_command():
	command = input(_PROMPT)
	if command in ['ls', 'quit']:
		return command
	elif command[:3] in ['get', 'put'] and len(command.split()) == 2:
		return command
	else:
		_err_log("Invalid command. " + _USAGE2)
		return ''


def execute_command(command):
	if command == 'quit':
		try:
			_SOCK.sendall(struct.pack('!HH', 4, 0) + b'quit')
		except OSError as e:
			_log("Error sending 'quit'")
		disconnect_and_exit()
	elif command == 'ls':
		ls()
	elif command[:3] == 'get':
		get(command)
	elif command[:3] == 'put':
		put(command)
	else:
		_err_log("Unexpected command: {}".format(command))


def ls():
	data_socket = pack_and_send('ls')
	data = recv(data_socket).decode('utf-8')
	shut(data_socket)
	status = _SOCK.recv(1)
	if not status or status == b'F':
		_log("Directory listing failed.")
	elif status == b'S':
		_log(data[:-1])
	else:
		_err_log("Unexpected status: {}".format(status))


def get(command):
	filename = command.split()[1]
	if os.path.exists(filename):
		_log("Cannot overwrite local files.")
		return
	data_socket = pack_and_send(command)
	data = recv(data_socket).decode('utf-8')
	shut(data_socket)
	status = _SOCK.recv(1)
	if not status or status == b'F':
		_log("File retrieval failed. (file may not exist)")
	elif status == b'S':
		with open(filename, 'w') as f:
			f.write(data)
		msg = "File: {0} [{1} bytes] downloaded.".format(filename, len(data))
		_log(msg)
	else:
		_err_log("Unexpected status: {}".format(status))


def put(command):
	filename = command.split()[1]
	if not os.path.exists(filename):
		_log("File does not exist.")
		return
	data_socket = pack_and_send(command)
	status = _SOCK.recv(1)
	if status == b'F':
		_log("Unable to upload {}. (cannot overwrite)".format(filename))
		shut(data_socket)
		return
	elif status != b'S':
		_log("Something happened.")
		shut(data_socket)
		disconnect_and_exit()
	data = ''
	with open(filename, 'r') as f:
		data = f.read()
	size_bytes = struct.pack('!I', len(data))
	data_socket.sendall(size_bytes + data.encode('utf-8'))
	shut(data_socket)
	status = _SOCK.recv(1)
	if not status or status == b'F':
		_log("File upload failed.")
	elif status == b'S':
		msg = "File: {0} [{1} bytes] uploaded.".format(filename, len(data))
		_log(msg)
	else:
		_err_log("Unexpected status: {}".format(status))


def recv(connection):
	try:
		size_bytes = connection.recv(4)
		if len(size_bytes) < 4:
			size_bytes += connection.recv(4 - len(size_bytes))
		if len(size_bytes) != 4:
			_err_log('recv failed.')
			disconnect_and_exit()
	except OSError as e:
		_err_log('recv failed.')
		disconnect_and_exit()
	n = struct.unpack('!I', size_bytes)[0]
	data = []
	num_bytes_read = 0
	while num_bytes_read < n:
		# Receive in chunks of 2048
		try:
			datum = connection.recv(min(n - num_bytes_read, 2048))
		except:
			connection.close()
			self.log('recv failed.')
			data = []
			raise
		data.append(datum)
		num_bytes_read += len(datum)
	return b''.join(data)


def pack_and_send(payload):
	if len(payload) > 65000:
		_err_log("Unable to send command to server. exiting...")
		disconnect_and_exit()
	#pack size into msg
	msg = struct.pack('!H', len(payload))
	data_socket = socket.socket()
	data_socket.bind((_HOST, 0))
	data_socket.listen(1)
	data_socket.settimeout(5)
	data_port = data_socket.getsockname()[1]
	#pack port into msg
	msg += struct.pack('!H', data_port)
	#pack payload into msg
	msg = msg + payload.encode('utf-8')
	_SOCK.sendall(msg)
	try:
		connection, addr = data_socket.accept()
	except socket.timeout:
		_err_log("Connection timed out...")
		raise
	except OSError:
		_err_log("Server did not make connection.")
		disconnect_and_exit()
	else:
		return connection


def shut(sock):
	try:
		sock.shutdown(socket.SHUT_RDWR)
		sock.close()
	except:
		pass
	sock = None


def disconnect_and_exit():
	shut(_SOCK)
	sys.exit(0)


def main():
	global _SOCK
	_SOCK = socket.socket()
	try:
		_SOCK.connect((_HOST, _PORT))
		_SOCK.settimeout(5)
	except OSError as e:
		_err_log("Unable to connect to " + _HOST)
		if e.errno == 61:
			_log("Check that the FTP server is running on the same port.")
			return
		else:
			raise
	running = True
	while running:
		try:
			command = get_command()
			if not command:
				continue
			try:
				execute_command(command)
			except socket.timeout as e:
				_log("Server not responsive... exiting.")
				disconnect_and_exit()
		except KeyboardInterrupt as e:
			try:
				_log("\nAttempting to send 'quit'")
				_SOCK.sendall(struct.pack('!HH', 4, 0) + b'quit')
				_log("Sent")
			except OSError as e2:
				pass
			_log("Closing connection...")
			disconnect_and_exit()


if __name__ == "__main__":
	check_args(sys.argv)
	main()

