import random

def run(payload: str = "ok") -> str:
    coffees = ["Cappuccino", "Espresso", "Latte", "Americano", "Flat White"]
    choice = random.choice(coffees)
    return f"Time for a {choice}! Go get one."
