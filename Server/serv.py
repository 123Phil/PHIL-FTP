#! /usr/local/bin/python3
""" Simplified FTP server
Author: Phillip Stewart

This is a custom FTP server that supports multiple simultaneous clients.
Each client is allocated a thread.
A threading.Lock object is used to protect files from race conditions.

The ClientThread class extends threading.Thread, and so calling .start()
	on the object begins thread execution and invokes the object's run() method

The os library is used to check file paths.
The sys library is used to gather command-line arguments.
The socket library is used for TCP socket connections.
The struct library is used to pack and unpack data to/from network bytes.
The subprocess library is used to invoke 'ls' and recover its output.

The PHIL-FTP protocol used is described in PHIL-FTP.txt
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
	"""ClientThread class extends threading.Thread
	This class represents the thread created for each client connected to the
	server. The methods defined here act on each individual client thread
	separately, however, the same file lock is passed to each thread.
	"""
	def __init__(self, connection, lock):
		"""Initialize an instance of ClientThread
		Args:
			connection - connected socket.socket object
			lock - threading.Lock object
		"""
		threading.Thread.__init__(self)
		self.connection = connection
		self.client_host = connection.getsockname()[0]
		self.file_lock = lock
		self.running = True
		self.command = ''
		self.filename = ''
		self.ephemeral = 0
		global _CLIENT_NUM
		self.ID = _CLIENT_NUM
		_CLIENT_NUM += 1

	def read_command(self):
		"""Read a command from the client
		First byte read is the length of the command.
		Then 2 bytes for ephemeral port.
		Then the command, which is saved to self.command
		"""
		size_bytes = self._recv(1)
		if not size_bytes:
			self.kill()
			return
		size = struct.unpack('!B', size_bytes)[0]
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
		"""Executes the command that was read by read_command"""
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
		"""Receives n bytes from self.connection"""
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
		"""Receives data from connection
		Args: connection - the socket connection from which to read
		The first 4 bytes of data define the size of the following data.
		"""
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
		A single byte status is sent over the control connection
			'S' for success, 'F' for failure.
		"""
		listing = b''
		with self.file_lock:
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
		"""Delivers a file over the data connection.
		Attempts to read file and send it over the data_socket
		The first 4 bytes of data define the size of the file.
		Upon successful delivery 'S' sent over control connection.
			else, 'F' sent.
		"""
		data = ''
		data_socket = socket.socket()
		data_socket.connect((self.client_host, self.ephemeral))
		if self.filename.startswith('.'):
			self.log("Client requesting a . file.")
			self.log("get FAILURE!")
			data_socket.sendall(struct.pack('!I', 0))
			self.connection.send(b'F')
			return
		elif not os.path.exists(self.filename):
			self.log("Client requesting non-existent file.")
			self.log("get FAILURE!")
			data_socket.sendall(struct.pack('!I', 0))
			self.connection.send(b'F')
			return
		with self.file_lock:
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
		"""Attempt to put a file.
		Connect to data socket.
		If can put, send 'S' and read data.
			else send 'F' and return
		If write success, send 'S'
			else send 'F'
		"""
		data_socket = socket.socket()
		data_socket.connect((self.client_host, self.ephemeral))
		with self.file_lock:
			if self.filename.startswith('.'):
				self.connection.send(b'F')
				self.log("Client attempting to put a . file.")
				self.log('put FAILURE!')
			elif os.path.exists(self.filename):
				self.connection.send(b'F')
				self.log("Client attempting to overwrite file.")
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
		"""Write a message to stdout"""
		client_msg = 'Client #' + str(self.ID) + ': ' + msg + '\n'
		sys.stdout.write(client_msg)
		sys.stdout.flush()

	def kill(self):
		"""Close connection, set running to False
		Does not actually kill thread,
			however, shutting down the socket and toggling the running flag
			should effectively stop thread execution very quickly.
		"""
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
		"""Begin thread execution
		This is a threading.Thread method which is invoked
			after the .start method is called.
		"""
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
	"""Write msg to stdout
	Yes, I could have used print statements everywhere...
		but I prefer writing my own log function for a number of reasons:
		-write and flush performs more reliably with multiple threads
		-abstracting out logging allows changing the logging method easily
			-such as logging to file.
		-split logging to stdout and stderr more clearly.
	Same goes for log method in ClientThread.
	"""
	sys.stdout.write(msg + '\n')
	sys.stdout.flush()


def _err_log(msg):
	"""Write msg to stderr"""
	sys.stderr.write(msg + '\n')
	sys.stderr.flush()


def check_args(args):
	"""Verify that an integer was supplied for port #"""
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
	"""The server's main function
	Bind, listen, and accept on supplied port.
	While accepting, create ClientThreads for each client connection.
	On CTRL+C - attempt to kill any running threads and exit.
	"""
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
		client = ClientThread(client_socket, _FILE_LOCK)
		client.start()
		clients.append(client)
		clients = [client for client in clients if client.is_alive()]
	for client in clients:
		client.kill()
		client.join()
	_log('Server shut down normally.')


if __name__ == "__main__":
	"""Standard main boiler-plate for python
	This ensures that main function does not execute on import
	-only run if this script was invoked as the main script.
	"""
	check_args(sys.argv)
	main()

