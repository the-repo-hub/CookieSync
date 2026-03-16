class HandleCommandError(Exception):
    """Command is missed, non-existing command, etc"""
    pass

class StorageError(Exception):
    """Errors with accounts operations"""
    pass
