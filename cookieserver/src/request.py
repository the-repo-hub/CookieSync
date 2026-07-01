from dataclasses import dataclass
from typing import Dict

from cookieserver.src.choices import Fields
from cookieserver.src.errors import HandleCommandError


@dataclass
class Request:
    payload: Dict

    def __post_init__(self):
        self.command = self.payload.get(Fields.command)
        self.account = self.payload.get(Fields.account)
        self.uuid = self.payload.get(Fields.uuid)
        self.payload = self.payload.get(Fields.payload)

        if not self.command:
            raise HandleCommandError("No command specified")
        if not self.account:
            raise HandleCommandError("No account specified")
        if not self.uuid:
            raise HandleCommandError("No uuid specified")
