import json


class Store:
    def __init__(self, connection_string):
        self.connection_string = connection_string

    def _read_data(self):
        with open(self.connection_string, "r", encoding="utf-8") as file:
            return json.load(file)

    def _write_data(self, data):
        with open(self.connection_string, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)

    def get_all_sandboxes(self):
        data = self._read_data()
        return data["sandboxes"]

    def add_sandbox_to_store(
        self,
        id: str,
        container_id: str,
        container_name: str,
        host_port: int,
    ):
        sandboxes = self.get_all_sandboxes()

        sandbox = {
            "id": id,
            "container_id": container_id,
            "container_name": container_name,
            "host_port": host_port,
        }

        sandboxes.append(sandbox)

        self._write_data({"sandboxes": sandboxes})

        return sandbox

    def get_sandbox_from_store(self, id: str):
        sandboxes = self.get_all_sandboxes()

        for sandbox in sandboxes:
            if sandbox["id"] == id:
                return sandbox

        raise ValueError(f"Sandbox {id} does not exist")

    def delete_sandbox_from_store(self, id: str):
        sandboxes = self.get_all_sandboxes()

        for index, sandbox in enumerate(sandboxes):
            if sandbox["id"] == id:
                deleted = sandboxes.pop(index)

                self._write_data({"sandboxes": sandboxes})

                return deleted

        raise ValueError(f"Sandbox {id} does not exist")


store = Store("data.json")
