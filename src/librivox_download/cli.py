"""Installed command line; same session-picker behavior as the checkout launcher."""

def main():
    from .launch import main as launch
    return launch(choose_session=True)
