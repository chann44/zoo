from server.server import Server

server = Server()
app = server.app


def main():

    server.start(import_string="main:app")

if __name__ == "__main__":
    main()
