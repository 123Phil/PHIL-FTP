""" Simplified FTP server
Author: Phillip Stewart



"""


import os
import sys
import socket
import struct
import subprocess
import threading


# Port is specified by command-line argument
_PORT = 20
_SOCK = None
_USAGE = "  Usage: python3 serv.py <PORT #>"
_FILE_LOCK = threading.Lock()
_CLIENT_NUM = 1


class ClientThread(threading.Thread):
	def __init__(self, connection):
		threading.Thread.__init__(self)
		self.connection = connection
		self.client_host = connection.getsockname()[0]
		self.running = True
		self.command = ''
		self.filename = ''
		self.ephemeral = 0
		global _CLIENT_NUM
		self.ID = _CLIENT_NUM
		_CLIENT_NUM += 1

	def read_command(self):
		size_bytes = self._recv(2)
		if not size_bytes:
			self.kill()
			return
		size = struct.unpack('!H', size_bytes)[0]
		port_bytes = self._recv(2)
		self.ephemeral = struct.unpack('!H', port_bytes)[0]
		command = self._recv(size).decode('utf-8')
		if command in ['ls', 'quit']:
			self.command = command
		elif command[:3] in ['get', 'put']:
			try:
				command, fn = command.split()
			except ValueError as e:
				# Too many arguments given
				self.log('error parsing: ' + command)
				self.kill()
				self.command = ''
				return
			self.command = command
			self.filename = fn
		else:
			_err_log('Received invalid command: ' + command)
			self.command = ''
			self.kill()

	def serve_command(self):
		if not self.command:
			self.kill()
			return
		if self.command == 'get':
			self.get()
		elif self.command == 'put':
			self.put()
		elif self.command == 'ls':
			self.ls()
		elif self.command == 'quit':
			self.log('quit SUCCESS!')
			self.connection.send(b'S')
			self.kill()
		else:
			self.log("Unexpected command: {}.".format(command))

	def _recv(self, n):
		data = []
		num_bytes_read = 0
		while num_bytes_read < n:
			# Receive in chunks of 2048
			if not self.connection:
				self.running = False
				return b''
			try:
				datum = self.connection.recv(min(n - num_bytes_read, 2048))
			except:
				self.kill()
				self.log('connection lost.')
				data = []
				return b''
			data.append(datum)
			num_bytes_read += len(datum)
		return b''.join(data)

	def _data_recv(self, connection):
		size_bytes = connection.recv(4)
		if len(size_bytes) < 4:
			size_bytes += connection.recv(4 - len(size_bytes))
		if len(size_bytes) != 4:
			connection.close()
			self.log('data upload failed.')
			return b''
		n = struct.unpack('!I', size_bytes)[0]
		data = []
		num_bytes_read = 0
		while num_bytes_read < n:
			# Receive in chunks of 2048
			try:
				datum = connection.recv(min(n - num_bytes_read, 2048))
			except:
				connection.close()
				self.log('data upload failed.')
				data = []
				return b''
			data.append(datum)
			num_bytes_read += len(datum)
		return b''.join(data)

	def ls(self):
		"""Send directory listing to client
		Nominally, this method will retrieve the listing,
			create an ephemeral connection,
			send the ephemeral port to the client,
			send the size of the listing (as a packed int)
			and then the listing 
		"""
		listing = b''
		with _FILE_LOCK:
			listing = subprocess.check_output('ls')
		if not listing:
			self.log("ls FAILURE!")
			self.connection.send(b'F')
		data_socket = socket.socket()
		data_socket.connect((self.client_host, self.ephemeral))
		data_size = len(listing)
		data_size_bytes = struct.pack('!I', data_size)
		data_socket.sendall(data_size_bytes + listing)
		self.log("ls SUCCESS!")
		self.connection.send(b'S')

	def get(self):
		data = ''
		data_socket = socket.socket()
		data_socket.connect((self.client_host, self.ephemeral))
		if not os.path.exists(self.filename):
			self.log("Client requesting non-existent file.")
			self.log("get FAILURE!")
			data_socket.sendall(struct.pack('!I', 0))
			self.connection.send(b'F')
			return
		with _FILE_LOCK:
			with open(self.filename, 'r') as f:
				data = f.read()
		data_size = len(data)
		data_size_bytes = struct.pack('!I', data_size)
		data_socket.sendall(data_size_bytes + data.encode('utf-8'))
		data_socket.shutdown(socket.SHUT_RDWR)
		data_socket.close()
		self.connection.send(b'S')
		self.log('get ' + self.filename + ' SUCCESS!')

	def put(self):
		data_socket = socket.socket()
		data_socket.connect((self.client_host, self.ephemeral))
		with _FILE_LOCK:
			if os.path.exists(self.filename):
				self.connection.send(b'F')
				self.log('put FAILURE!')
			else:
				self.connection.send(b'S')
				try:
					data = self._data_recv(data_socket).decode('utf-8')
					with open(self.filename, 'w') as f:
						f.write(data)
				except:
					self.connection.send(b'F')
					self.log('put FAILURE!')
				else:
					self.connection.send(b'S')
					self.log('put ' + self.filename + ' SUCCESS!')
		try:
			data_socket.shutdown(socket.SHUT_RDWR)
			data_socket.close()
		except:
			pass
		

	def log(self, msg):
		client_msg = 'Client #' + str(self.ID) + ': ' + msg + '\n'
		sys.stdout.write(client_msg)
		sys.stdout.flush()

	def kill(self):
		self.running = False
		self.command = ''
		if not self.connection:
			return
		try:
			self.connection.shutdown(socket.SHUT_RDWR)
			self.connection.close()
		except OSError as e:
			pass
		finally:
			self.connection = None

	def run(self):
		self.log('starting.')
		while self.running:
			self.read_command()
			self.serve_command()
		try:
			self.connection.shutdown(socket.SHUT_RDWR)
			self.connection.close()
		except:
			pass
		self.connection = None
		self.log('terminating.')


def _log(msg):
	sys.stdout.write(msg + '\n')
	sys.stdout.flush()


def _err_log(msg):
	sys.stderr.write(msg + '\n')
	sys.stderr.flush()


def check_args(args):
	global _PORT
	if len(args) != 2:
		_log(_USAGE)
		sys.exit(0)
	try:
		_PORT = int(args[1])
	except ValueError as e:
		_err_log("Invalid port number supplied\n" + _USAGE)
		sys.exit(1)


def main():
	global _SOCK
	_SOCK = socket.socket()
	clients = []
	client_socket = None
	try:
		#The following is helpful if frequently restarting server.
		#_SOCK.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		_SOCK.bind(('localhost', _PORT))
		_SOCK.listen(5)
	except OSError as e:
		#_err_log(str(e))
		_err_log("Unable to connect to port: {}\n".format(_PORT))
		sys.exit(1)
	_log("Server accepting connections on port {}.".format(_PORT))
	_log("Exit the server with CTRL+C")
	while True:
		try:
			# Accept blocks until incoming connection
			client_socket, addr = _SOCK.accept()
		except KeyboardInterrupt as e:
			_log("\nShutting down server...")
			break
		client = ClientThread(client_socket)
		client.start()
		clients.append(client)
		clients = [client for client in clients if client.is_alive()]
	for client in clients:
		client.kill()
		client.join()
	_log('Server shut down normally.')


if __name__ == "__main__":
	check_args(sys.argv)
	main()

