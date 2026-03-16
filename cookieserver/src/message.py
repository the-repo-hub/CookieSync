from cookieserver.src.errors import HandleCommandError
from cookieserver.src.choices import Fields
from typing import Dict
from dataclasses import dataclass

@dataclass
class Message:
    raw_data: Dict

    def __post_init__(self):
        self.command = self.raw_data.get(Fields.command)
        self.account = self.raw_data.get(Fields.account)
        self.request_id = self.raw_data.get(Fields.request_id)

        if not self.command:
            raise HandleCommandError("No command specified")
        if not self.account:
            raise HandleCommandError("No account specified")
        if not self.request_id:
            raise HandleCommandError("No request_id specified")

        self.payload = self.raw_data.get(Fields.payload)
