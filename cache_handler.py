import os
import json
import time

class CacheHandler:

    DATA_RETENTION = 60 * 60 * 24 * 7

    def __init__(self, directory: str) -> None:
        self._directory = directory

    def invalidate_all(self) -> None:
        for filename in os.listdir(self._directory):
            file_path = os.path.join(self._directory, filename)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            except Exception as e:
                print(f"Error deleting file {file_path}: {str(e)}")

    def invalidate_key(self, key: str) -> None:
        key = key.lower().strip()
        if not key.endswith(".json"):
            key = key + ".json"
        file_path = os.path.join(self._directory, key)
        try:
            if os.path.isfile(file_path):
                os.unlink(file_path)
        except Exception as e:
            print(f"Error deleting file {file_path}: {str(e)}")

    def retrieve(self, key: str) -> dict|None:
        key = key.lower().strip()
        if not key.endswith(".json"):
            key = key + ".json"
        file_path = os.path.join(self._directory, key)
        if os.path.isfile(file_path):
            if os.path.getmtime(file_path) < (time.time() - self.DATA_RETENTION):
                try:
                    os.unlink(file_path)
                except Exception as e:
                    print(f"Error deleting file {file_path}: {str(e)}")
                return None
            try:
                with open(file_path, "r") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error reading file {file_path}: {str(e)}")
                return None
        else:
            return None

    def store(self, key: str, data: dict|None) -> None:
        key = key.lower().strip()
        if not key.endswith(".json"):
            key = key + ".json"
        file_path = os.path.join(self._directory, key)
        try:
            with open(file_path, "w") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"Error writing file {file_path}: {str(e)}")
