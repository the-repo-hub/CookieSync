from typing import List, Dict

class Cookies:

    def __init__(self, cookies_lst: List[Dict]):
        self.cookies_lst = cookies_lst
        value1 = cookies_lst[0].get('value')
        value2 = cookies_lst[1].get('value')
        self.reso60 = value1
        self.aspnet = value2
        if len(value1) < len(value2):
            self.reso60 = value2
            self.aspnet = value1

    def __eq__(self, other):
        return self.reso60 == other.reso60 and self.aspnet == other.aspnet

    def as_lst(self) -> List[Dict]:
        return self.cookies_lst
