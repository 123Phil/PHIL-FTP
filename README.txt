Phillip Stewart - Sole developer.
phillipwstewart@gmail.com

FTP Client/Server in Python 3

To run the program:
  - Run the server:
    Navigate to the Server directory in a terminal.
    Enter the command:
    $ python3 serv.py <port>
    where <port> is the port number for the server to bind.
    - Alternatively (if python3 exists at /usr/local/bin/):
      $ ./serv.py <port>

  - Run a client:
    Navigate to the Client directory in a terminal.
    Enter the command:
    $ python3 cli.py <host> <port>
    where <host> is the address of the server (localhost if on the same machine)
    and <port> is the port number on which the server is running.
    - Alternatively (if python3 exists at /usr/local/bin/):
      $ ./cli.py <host> <port>
    The server program must be running prior to running a client.
    Multiple clients may run simultaneously.

The client and server write to stdout, so you should not background the tasks.
The implementation does not allow overwriting and does not allow calling
  get or put with . files (no hidden files or files in higher directories).
The server uses a lock to ensure proper operation with multiple clients.
The server can be shutdown with CTRL+C.
The client should be closed by entering 'quit', but CTRL+C should accomplish the same.

Protocol design is outlined in PHIL-FTP.txt
  -The format is similar to other RFC documents.

A few sample files have been left for testing ls, get, and put.

Enjoy!
