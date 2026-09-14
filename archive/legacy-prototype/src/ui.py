import sys
import os
import tkinter as tk
from tkinter import messagebox

# Ensure repo root is on sys.path so `src` package can be imported when running this file directly
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from src.engine import Card, Deck, Player
import random


def make_sample_player():
    cards = [Card(id=str(i), name=f"Strike {i+1}", data={"damage": 2 + i}) for i in range(8)]
    deck = Deck(cards[:])
    deck.shuffle()
    player = Player("You", deck=deck)
    player.draw(5)
    return player


def make_two_players():
    # Player (bottom) and Opponent (top)
    p_cards = [Card(id=f"p{i}", name=f"P{ i+1 }Strike", data={"damage": 2 + (i % 3)}) for i in range(10)]
    # opponent should have playable damage cards so AI can act
    o_cards = [Card(id=f"o{i}", name=f"O{i+1}Strike", data={"damage": 1 + (i % 3)}) for i in range(10)]

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
            # pass self so caller can remove the widget
            self.play_callback(self, self.card)


def main():
    player, opponent = make_two_players()

    root = tk.Tk()
    root.title("Card Game — Two Player View")

    # helper to load sample deck from data/cards.json
    def load_sample_deck():
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        cards_path = os.path.join(repo_root, 'data', 'cards.json')
        from src.engine import load_cards_from_file
        cards = load_cards_from_file(cards_path)
        if not cards:
            messagebox.showwarning("Load Deck", "No cards found in data/cards.json")
            return
        # replace player's deck and redraw UI by restarting app (simple approach)
        player.deck = Deck(cards[:])
        player.hand = []
        player.discard = []
        player.draw(5)
        # rebuild the window: for simplicity, destroy and re-run main
        root.destroy()
        main()


    # Opponent area (top)
    top_frame = tk.Frame(root)
    top_frame.pack(side="top", fill="x", pady=8)

    # small control bar
    ctrl = tk.Frame(root)
    ctrl.pack()
    tk.Button(ctrl, text="Load Sample Deck", command=load_sample_deck).pack(side="left", padx=6)
    def ai_turn_action():
        # let the opponent (AI) take a turn using the Game controller
        from src.ai import SimpleAI
        # ensure opponent draws at start of AI turn (draw phase)
        try:
            opponent.draw(1)
        except Exception:
            pass
        # pick a card via AI heuristic
        card = SimpleAI.choose_damage_card(opponent)
        if card:
            try:
                game.play_card(opponent, card, target=player)
                messagebox.showinfo("AI", f"AI played {card.name}")
                # update player HP (after resolving)
                game.resolve_stack()
                try:
                    p_hp_label.config(text=str(player.hp))
                except NameError:
                    pass
                try:
                    opp_deck_count.config(text=str(opponent.deck.count()))
                except NameError:
                    pass
                # update opponent discard count display
                try:
                    opp_discard_label.config(text=str(len(opponent.discard)))
                except NameError:
                    pass
            except Exception as e:
                messagebox.showerror("AI Error", str(e))
        else:
            messagebox.showinfo("AI", "AI had no playable card")

    tk.Button(ctrl, text="AI Turn", command=ai_turn_action).pack(side="left", padx=6)

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
    tk.Label(opp_deck_frame, text="HP:").pack()
    opp_hp_label = tk.Label(opp_deck_frame, text=str(opponent.hp), font=("Arial", 12))
    opp_hp_label.pack()
    tk.Label(opp_deck_frame, text="Discard:").pack()
    opp_discard_label = tk.Label(opp_deck_frame, text=str(len(opponent.discard)), font=("Arial", 12))
    opp_discard_label.pack()

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

    # player's deck & discard counts
    p_deck_frame = tk.Frame(player_info)
    p_deck_frame.pack(side="right", padx=10)
    tk.Label(p_deck_frame, text="Deck:").pack()
    p_deck_count = tk.Label(p_deck_frame, text=str(player.deck.count()), font=("Arial", 12))
    p_deck_count.pack()
    tk.Label(p_deck_frame, text="HP:").pack()
    p_hp_label = tk.Label(p_deck_frame, text=str(player.hp), font=("Arial", 12))
    p_hp_label.pack()
    tk.Label(p_deck_frame, text="Discard:").pack()
    p_discard_count = tk.Label(p_deck_frame, text=str(len(player.discard)), font=("Arial", 12))
    p_discard_count.pack()

    # hand
    hand_frame = tk.Frame(player_info)
    hand_frame.pack(side="left", padx=10)

    # create a game controller
    from src.engine import Game
    game = Game([player, opponent])

    def play_card(widget, card):
        try:
            game.play_card(player, card, target=opponent)
        except Exception as e:
            messagebox.showerror("Play Error", f"Could not play card: {e}")
            return

        # show confirmation and move the visual card to the play area
        messagebox.showinfo("Play", f"You played {card.name} (data: {card.data})")
        try:
            # create a small visual representation in the center play area
            pe = tk.Frame(center, bd=1, relief="sunken", padx=6, pady=4)
            tk.Label(pe, text=card.name).pack()
            pe.pack(side="left", padx=6)
            # attach widget so we can remove later when resolved
            widget.play_preview = pe
            widget.destroy()
        except Exception:
            pass

        # resolve immediately for now and update UI
        try:
            game.resolve_stack()
        except Exception:
            pass

        # update UI labels after resolution
        p_discard_count.config(text=str(len(player.discard)))
        try:
            opp_hp_label.config(text=str(opponent.hp))
            opp_discard_label.config(text=str(len(opponent.discard)))
            p_hp_label.config(text=str(player.hp))
        except Exception:
            pass

    for c in player.hand:
        cw = CardWidget(hand_frame, c, play_callback=play_card)
        cw.pack(side="left", padx=6)

    root.mainloop()


if __name__ == "__main__":
    main()
