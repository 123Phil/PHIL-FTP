#! /usr/local/bin/python3
""" Simplified FTP client
Author: Phillip Stewart

This is a custom FTP client that connects to the accompanying server.

If running the server and client on the same machine,
	use 'localhost' as host name.
	else, use the name of the server.

The user is given a prompt, and entered commands are parsed.
	valid commands are sent to the server,
	and data is transferred over a separate connection.

The os library is used to check file paths.
The sys library is used to gather command-line arguments.
The socket library is used for TCP socket connections.
The struct library is used to pack and unpack data to/from network bytes.

The PHIL-FTP protocol used is described in PHIL-FTP.txt
"""


import os
import sys
import socket
import struct


_SOCK = None
# Host is specified by command-line argument
_HOST = 'localhost'
# Port is specified by command-line argument
_PORT = 20
_USAGE = "  Usage: python3 cli.py <HOST> <PORT #>"
_USAGE2 = """Valid commands are:
  ls
  get <filename>
  put <filename>
  quit"""
_PROMPT = 'ftp> '


def _log(msg):
	"""Write msg to stdout
	Yes, I could have used print statements everywhere...
		but I prefer writing my own log function for a number of reasons:
		-write and flush performs more reliably with multiple threads
		-abstracting out logging allows changing the logging method easily
		-split logging to stdout and stderr more clearly.
	"""
	sys.stdout.write(msg + '\n')
	sys.stdout.flush()


def _err_log(msg):
	"""Write msg to stderr"""
	sys.stderr.write(msg + '\n')
	sys.stderr.flush()


def check_args(args):
	"""Verify command line arguments"""
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
	"""Read and verify a user command
	Allowed commands are:
		ls
		get <filename>
  		put <filename>
		quit"
	"""
	command = input(_PROMPT)
	if command in ['ls', 'quit']:
		return command
	elif command[:3] in ['get', 'put'] and len(command.split()) == 2:
		return command
	else:
		_err_log("Invalid command. " + _USAGE2)
		return ''


def execute_command(command):
	"""Run the command"""
	if command == 'quit':
		try:
			_SOCK.sendall(struct.pack('!BH', 4, 0) + b'quit')
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
	"""Send ls command and download listing"""
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
	"""Send get command and download file."""
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
	"""Send put command to server and upload file.
	Server sends 'S' if file upload is allowed,
	Then sends another 'S' if upload is successful.
	"""
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
	"""Receives a message over the connection
	First 4 bytes denote length of message.
	"""
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
	"""Send a command message to server.
	First byte is size of msg,
	Then two bytes denote the new data port.
	The message payload follows.
	-Attempts to accept server connection over data port,
		and returns the data connection.
	"""
	if len(payload) > 255:
		_err_log("Unable to send command to server. exiting...")
		disconnect_and_exit()
	#pack size into msg
	msg = struct.pack('!B', len(payload))
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
	"""Attempt to shutdown/close and null socket"""
	try:
		sock.shutdown(socket.SHUT_RDWR)
		sock.close()
	except:
		pass
	sock = None


def disconnect_and_exit():
	"""Shutdown the socket and hard-exit"""
	shut(_SOCK)
	sys.exit(0)


def main():
	"""Main function for client program
	Attempt to connect to server.
	Loop and get command from user
		execute valid commands.
	"""
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
				_SOCK.sendall(struct.pack('!BH', 4, 0) + b'quit')
				_log("Sent")
			except OSError as e2:
				pass
			_log("Closing connection...")
			disconnect_and_exit()


if __name__ == "__main__":
	"""Standard main boiler-plate for python
	This ensures that main function does not execute on import
	-only run if this script was invoked as the main script.
	"""
	check_args(sys.argv)
	main()

