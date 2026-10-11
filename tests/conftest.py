import keyring
import pytest
from keyring.backend import KeyringBackend


class InMemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self._data = {}

    def set_password(self, service, username, password):
        self._data[(service, username)] = password

    def get_password(self, service, username):
        return self._data.get((service, username))

    def delete_password(self, service, username):
        self._data.pop((service, username), None)


@pytest.fixture(autouse=True)
def memory_keyring():
    backend = InMemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
