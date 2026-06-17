import sys
import os
import tkinter as tk
from tkinter import messagebox

# Ensure repo root is on sys.path so `src` package can be imported when running this file directly
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from src.card_file import BASE_STARTER_DECK_CARDS
from src.engine import Card, Deck, Player
import random


def build_base_starter_deck(card_id_prefix: str):
    cards = []
    index = 0
    for definition in BASE_STARTER_DECK_CARDS:
        for _ in range(definition["count"]):
            cards.append(
                Card(
                    id=f"{card_id_prefix}{index}",
                    name=definition["name"],
                    data={
                        "damage": definition["damage"],
                        "bonus_resources": definition["bonus_resources"],
                    },
                )
            )
            index += 1
    return cards


def make_sample_player():
    cards = build_base_starter_deck("sample-")
    deck = Deck(cards[:])
    deck.shuffle()
    player = Player("You", deck=deck)
    player.draw(5)
    return player


def make_two_players():
    # Player (bottom) and Opponent (top)
    p_cards = build_base_starter_deck("p")
    o_cards = build_base_starter_deck("o")

    p_deck = Deck(p_cards[:])
    o_deck = Deck(o_cards[:])
    p_deck.shuffle()
    o_deck.shuffle()

    player = Player("You", deck=p_deck)
    opponent = Player("Opponent", deck=o_deck)

    # draw hands
    player.draw(5)
    # opponent hand is hidden — simulate by drawing to their hand but we will not reveal
    opponent.draw(3)

    return player, opponent


class CardWidget(tk.Frame):
    def __init__(self, master, card, play_callback=None):
        super().__init__(master, bd=2, relief="raised", padx=8, pady=6)
        self.card = card
        self.play_callback = play_callback
        # create a small canvas as a basic image for the card
        self.canvas = tk.Canvas(self, width=80, height=100, highlightthickness=0)
        self.canvas.pack()
        # draw a colored rectangle and name text
        color = "#%02x%02x%02x" % (150, 200, 240)
        self.canvas.create_rectangle(4, 4, 76, 96, fill=color, outline="black")
        self.canvas.create_text(40, 20, text=card.name, font=("Arial", 9), width=68)
        # show simple stats below
        if isinstance(card.data, dict) and card.data:
            stats = ", ".join(f"{k}:{v}" for k, v in card.data.items())
            self.canvas.create_text(40, 70, text=stats, font=("Arial", 9))

        self.btn = tk.Button(self, text="Play", command=self.on_play)
        self.btn.pack(pady=(6, 0))

    def on_play(self):
        if self.play_callback:
            self.play_callback(self.card)


def main():
    player, opponent = make_two_players()

    root = tk.Tk()
    root.title("Card Game — Two Player View")

    # Opponent area (top)
    top_frame = tk.Frame(root)
    top_frame.pack(side="top", fill="x", pady=8)

    opp_label = tk.Label(top_frame, text=f"Opponent: {opponent.name}", font=("Arial", 14))
    opp_label.pack()

    opp_info = tk.Frame(top_frame)
    opp_info.pack()
    # deck/back placeholder
    def make_card_back(parent):
        f = tk.Frame(parent, bd=1, relief="solid")
        cv = tk.Canvas(f, width=60, height=90, highlightthickness=0)
        cv.create_rectangle(4, 4, 56, 86, fill="#888888")
        cv.create_text(30, 45, text="BACK", fill="white")
        cv.pack()
        return f

    # show opponent hand as backs
    opp_hand_frame = tk.Frame(opp_info)
    opp_hand_frame.pack(side="left", padx=10)
    for _ in range(opponent.hand_size()):
        b = make_card_back(opp_hand_frame)
        b.pack(side="left", padx=4)

    # deck count
    opp_deck_frame = tk.Frame(opp_info)
    opp_deck_frame.pack(side="left", padx=20)
    tk.Label(opp_deck_frame, text="Deck:").pack()
    opp_deck_count = tk.Label(opp_deck_frame, text=str(opponent.deck.count()), font=("Arial", 12))
    opp_deck_count.pack()

    # Center play area
    center = tk.Frame(root, height=120)
    center.pack(fill="x", pady=12)

    # Player area (bottom)
    bottom_frame = tk.Frame(root)
    bottom_frame.pack(side="bottom", fill="x", pady=8)

    player_label = tk.Label(bottom_frame, text=f"Player: {player.name}", font=("Arial", 14))
    player_label.pack()

    player_info = tk.Frame(bottom_frame)
    player_info.pack()

    # player's deck count
    p_deck_frame = tk.Frame(player_info)
    p_deck_frame.pack(side="right", padx=10)
    tk.Label(p_deck_frame, text="Deck:").pack()
    p_deck_count = tk.Label(p_deck_frame, text=str(player.deck.count()), font=("Arial", 12))
    p_deck_count.pack()

    # hand
    hand_frame = tk.Frame(player_info)
    hand_frame.pack(side="left", padx=10)

    def play_card(card):
        messagebox.showinfo("Play", f"You played {card.name} (data: {card.data})")
        # after playing, remove from UI and update deck counts if needed

    for c in player.hand:
        cw = CardWidget(hand_frame, c, play_callback=play_card)
        cw.pack(side="left", padx=6)

    root.mainloop()


if __name__ == "__main__":
    main()
