from dataclasses import dataclass
from typing import Dict

from cookieserver.src.choices import Fields
from cookieserver.src.client import Client
from cookieserver.src.errors import HandleCommandError


@dataclass
class Request:
    raw_data: Dict
    client: Client

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
