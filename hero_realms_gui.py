"""Hero Realms GUI - Simple Tkinter interface to play against AI."""

import tkinter as tk
from tkinter import messagebox, scrolledtext
from hero_engine import load_hero_cards, buy_card, expend_champion
from hero_rl_env import HeroRealmsEnv
from pathlib import Path


class HeroRealmsGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Hero Realms - Play vs AI")
        self.root.geometry("1200x800")
        self.root.config(bg="#ecf0f1")
        
        # Load cards
        self.cards = load_hero_cards("data/hero_realms_cards.json")
        self.env = None
        self.game_over = False
        
        # Create GUI
        self._create_widgets()

    def _create_widgets(self):
        """Create GUI elements."""
        # Title
        title = tk.Label(self.root, text="Hero Realms - Play vs AI",
                        font=("Arial", 18, "bold"), bg="#ecf0f1", fg="#2c3e50")
        title.pack(pady=10)
        
        # Status
        self.status_label = tk.Label(self.root, text="Click 'Start Game' to begin",
                                    font=("Arial", 12), bg="#ecf0f1")
        self.status_label.pack(pady=5)
        
        # Main game frame
        game_frame = tk.Frame(self.root, bg="white", relief=tk.RIDGE, bd=2)
        game_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Opponent info (top)
        opp_frame = tk.Frame(game_frame, bg="#bdc3c7", height=50)
        opp_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
        opp_frame.pack_propagate(False)
        
        tk.Label(opp_frame, text="OPPONENT", font=("Arial", 11, "bold"),
                bg="#bdc3c7", fg="white").pack(side=tk.LEFT, padx=15, pady=10)
        self.opp_hp = tk.Label(opp_frame, text="HP: 50", font=("Arial", 10),
                              bg="#bdc3c7", fg="white")
        self.opp_hp.pack(side=tk.LEFT, padx=20)
        self.opp_gold = tk.Label(opp_frame, text="Gold: 0", font=("Arial", 10),
                                bg="#bdc3c7", fg="white")
        self.opp_gold.pack(side=tk.LEFT, padx=5)
        self.opp_combat = tk.Label(opp_frame, text="Combat: 0", font=("Arial", 10),
                                  bg="#bdc3c7", fg="white")
        self.opp_combat.pack(side=tk.LEFT, padx=5)
        
        # Market section
        market_label = tk.Label(game_frame, text="MARKET (Click to buy)", 
                               font=("Arial", 11, "bold"), bg="white")
        market_label.pack(pady=10)
        
        self.market_frame = tk.Frame(game_frame, bg="white")
        self.market_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Hand section
        champ_label = tk.Label(game_frame, text="CHAMPIONS", font=("Arial", 11, "bold"),
                      bg="white")
        champ_label.pack(pady=(10, 5))

        champ_container = tk.Frame(game_frame, bg="white")
        champ_container.pack(fill=tk.X, padx=10, pady=5)

        self.player_champ_frame = tk.LabelFrame(champ_container, text="Your Champions",
                            bg="#eaf7ee", fg="#1e8449",
                            font=("Arial", 9, "bold"), bd=2)
        self.player_champ_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=3)

        self.opp_champ_frame = tk.LabelFrame(champ_container, text="Opponent Champions",
                             bg="#fdecea", fg="#922b21",
                             font=("Arial", 9, "bold"), bd=2)
        self.opp_champ_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=3)

        # Hand section
        hand_label = tk.Label(game_frame, text="YOUR HAND", font=("Arial", 11, "bold"),
                             bg="white")
        hand_label.pack(pady=(20, 10))
        
        self.hand_frame = tk.Frame(game_frame, bg="white")
        self.hand_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Player info (bottom)
        player_frame = tk.Frame(game_frame, bg="#e8f5e9", height=50)
        player_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=5)
        player_frame.pack_propagate(False)
        
        tk.Label(player_frame, text="YOU", font=("Arial", 11, "bold"),
                bg="#e8f5e9", fg="#27ae60").pack(side=tk.LEFT, padx=15, pady=10)
        self.player_hp = tk.Label(player_frame, text="HP: 50", font=("Arial", 10),
                                 bg="#e8f5e9", fg="#27ae60")
        self.player_hp.pack(side=tk.LEFT, padx=20)
        self.player_gold = tk.Label(player_frame, text="Gold: 0", font=("Arial", 10),
                                   bg="#e8f5e9", fg="#f39c12")
        self.player_gold.pack(side=tk.LEFT, padx=5)
        self.player_combat = tk.Label(player_frame, text="Combat: 0", font=("Arial", 10),
                                     bg="#e8f5e9", fg="#e74c3c")
        self.player_combat.pack(side=tk.LEFT, padx=5)
        
        # Buttons
        button_frame = tk.Frame(self.root, bg="#ecf0f1")
        button_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.start_btn = tk.Button(button_frame, text="Start Game",
                                  command=self._start_game,
                                  font=("Arial", 11, "bold"),
                                  bg="#27ae60", fg="white",
                                  padx=15, pady=8, width=15)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        
        self.end_turn_btn = tk.Button(button_frame, text="End Turn",
                                     command=self._end_turn,
                                     font=("Arial", 11, "bold"),
                                     bg="#3498db", fg="white",
                                     padx=15, pady=8, width=15, state=tk.DISABLED)
        self.end_turn_btn.pack(side=tk.LEFT, padx=5)
        
        self.quit_btn = tk.Button(button_frame, text="Quit",
                                 command=self.root.quit,
                                 font=("Arial", 11),
                                 bg="#e74c3c", fg="white",
                                 padx=15, pady=8, width=15)
        self.quit_btn.pack(side=tk.RIGHT, padx=5)

    def _start_game(self):
        """Start a new game."""
        self.env = HeroRealmsEnv(self.cards, max_steps=500)
        # reset() constructs agent/opponent/market state used by the GUI
        self.env.reset()
        self.game_over = False
        self._update_display()
        self.status_label.config(text="Game started! Buy cards from the market and end your turn.")
        self.start_btn.config(state=tk.DISABLED)
        self.end_turn_btn.config(state=tk.NORMAL)

    def _update_display(self):
        """Update all display elements."""
        if not self.env:
            return
        
        p1 = self.env.agent
        p2 = self.env.opponent
        
        # Update stats
        self.player_hp.config(text=f"HP: {p1.hp}")
        self.player_gold.config(text=f"Gold: {p1.gold}")
        self.player_combat.config(text=f"Combat: {p1.combat}")
        
        self.opp_hp.config(text=f"HP: {p2.hp}")
        self.opp_gold.config(text=f"Gold: {p2.gold}")
        self.opp_combat.config(text=f"Combat: {p2.combat}")
        
        # Draw market
        self._draw_market()

        # Draw champions
        self._draw_champions()
        
        # Draw hand
        self._draw_hand()

    def _format_effects(self, card):
        """Build readable effect strings for card visuals."""
        effects = []
        if card.get("gold") > 0:
            effects.append(f"+{card.get('gold')} Gold")
        if card.get("combat") > 0:
            effects.append(f"+{card.get('combat')} Combat")
        if card.get("health") > 0:
            effects.append(f"+{card.get('health')} Health")
        if card.get("draw") > 0:
            effects.append(f"Draw {card.get('draw')}")
        if card.get("opponent_discard") > 0:
            effects.append(f"Opponent discards {card.get('opponent_discard')}")
        if card.get("sacrifice_combat") > 0:
            effects.append(f"Sacrifice: +{card.get('sacrifice_combat')} Combat")
        if card.get("stun", False):
            effects.append("Stun a champion")
        if card.get("prepare", False):
            effects.append("Ready a champion")
        if card.get("ally_draw") > 0:
            effects.append(f"Ally: Draw {card.get('ally_draw')}")
        if card.get("ally_combat") > 0:
            effects.append(f"Ally: +{card.get('ally_combat')} Combat")
        if card.get("ally_gold") > 0:
            effects.append(f"Ally: +{card.get('ally_gold')} Gold")
        if card.get("ally_health") > 0:
            effects.append(f"Ally: +{card.get('ally_health')} Health")
        if card.get("top_of_deck", False):
            effects.append("Ally: Next buy to top of deck")
        if card.get("to_hand", False):
            effects.append("Ally: Next buy to hand")
        if card.get("recycle", False):
            effects.append("Recycle from discard")
        if card.get("reanimate", False):
            effects.append("Reanimate champion")
        if card.card_type == "champion":
            hp_text = f"Champion HP {card.health}"
            if card.guard:
                hp_text += " (Guard)"
            effects.insert(0, hp_text)
        if not effects:
            return "No listed effects"
        return " | ".join(effects)

    def _draw_market(self):
        """Draw market cards."""
        for widget in self.market_frame.winfo_children():
            widget.destroy()

        for i, card in enumerate(self.env.market.row):
            if card is None:
                continue

            frame = tk.Frame(self.market_frame, bg="#3498db", relief=tk.RAISED, bd=2)
            frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=3, pady=3)

            # Card name
            name = tk.Label(frame, text=card.name, font=("Arial", 9, "bold"),
                            bg="#3498db", fg="white", wraplength=70)
            name.pack(padx=5, pady=3)

            # Cost
            cost = tk.Label(frame, text=f"Cost: {card.cost}", font=("Arial", 8),
                            bg="#2980b9", fg="white")
            cost.pack(fill=tk.X, padx=5, pady=2)

            # Card metadata and effects
            meta = f"{card.faction or 'Neutral'} | {card.card_type.title()}"
            tk.Label(frame, text=meta, font=("Arial", 7, "italic"),
                     bg="#3498db", fg="#ecf0f1", wraplength=70).pack(padx=3, pady=1)

            effects_text = self._format_effects(card)
            effects_label = tk.Label(frame, text=effects_text, font=("Arial", 7),
                                     bg="#3498db", fg="white", wraplength=70)
            effects_label.pack(padx=3, pady=2)

            # Buy button
            can_afford = card.cost <= self.env.agent.gold
            btn_color = "#27ae60" if can_afford else "#95a5a6"
            buy_btn = tk.Button(frame, text="Buy",
                                command=lambda idx=i: self._buy_card(idx),
                                bg=btn_color, fg="white", font=("Arial", 8),
                                state=tk.NORMAL if can_afford else tk.DISABLED)
            buy_btn.pack(fill=tk.X, padx=3, pady=2)

        # Fire Gem side pile (always available while pile remains)
        gem_frame = tk.Frame(self.market_frame, bg="#e67e22", relief=tk.RAISED, bd=2)
        gem_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=3, pady=3)

        tk.Label(gem_frame, text="Fire Gem", font=("Arial", 9, "bold"),
                 bg="#e67e22", fg="white", wraplength=70).pack(padx=5, pady=3)
        tk.Label(gem_frame, text="Cost: 2", font=("Arial", 8),
                 bg="#d35400", fg="white").pack(fill=tk.X, padx=5, pady=2)
        tk.Label(gem_frame, text=f"Pile: {self.env.market.fire_gems_remaining}", font=("Arial", 7),
                 bg="#e67e22", fg="white", wraplength=70).pack(padx=3, pady=2)
        tk.Label(gem_frame, text="+2 Gold | Sacrifice: +3 Combat", font=("Arial", 7),
                 bg="#e67e22", fg="white", wraplength=70).pack(padx=3, pady=2)

        can_buy_gem = self.env.agent.gold >= 2 and self.env.market.can_buy_fire_gem()
        gem_btn_color = "#27ae60" if can_buy_gem else "#95a5a6"
        tk.Button(gem_frame, text="Buy",
                  command=lambda: self._buy_card(5),
                  bg=gem_btn_color, fg="white", font=("Arial", 8),
                  state=tk.NORMAL if can_buy_gem else tk.DISABLED).pack(fill=tk.X, padx=3, pady=2)

    def _draw_champions(self):
        """Draw both players' champion boards and champion actions."""
        for widget in self.player_champ_frame.winfo_children():
            widget.destroy()
        for widget in self.opp_champ_frame.winfo_children():
            widget.destroy()

        player_champs = [bc for bc in self.env.agent.board if bc.alive]
        opp_champs = [bc for bc in self.env.opponent.board if bc.alive]

        if not player_champs:
            tk.Label(self.player_champ_frame, text="No champions in play",
                     font=("Arial", 9), bg="#eaf7ee", fg="#7f8c8d").pack(pady=8)
        else:
            for bc in player_champs:
                bg = "#d5f5e3" if not bc.exhausted else "#f0f3f4"
                frame = tk.Frame(self.player_champ_frame, bg=bg, relief=tk.RIDGE, bd=1)
                frame.pack(fill=tk.X, padx=4, pady=3)

                status = "Ready" if not bc.exhausted else "Exhausted"
                guard = "Guard" if bc.guard else ""
                title = f"{bc.name}  HP {bc.current_health}/{bc.card.health}  {guard}  {status}".strip()
                tk.Label(frame, text=title, font=("Arial", 8, "bold"),
                         bg=bg, fg="#1f618d", anchor="w", justify=tk.LEFT).pack(fill=tk.X, padx=4, pady=2)

                tk.Label(frame, text=self._format_effects(bc.card), font=("Arial", 7),
                         bg=bg, fg="#2c3e50", wraplength=430, anchor="w", justify=tk.LEFT).pack(fill=tk.X, padx=4)

                can_expend = not bc.exhausted
                tk.Button(frame, text="Expend",
                          command=lambda champ=bc: self._expend_champion(champ),
                          bg="#27ae60" if can_expend else "#95a5a6", fg="white", font=("Arial", 8),
                          state=tk.NORMAL if can_expend else tk.DISABLED).pack(anchor="e", padx=4, pady=3)

        if not opp_champs:
            tk.Label(self.opp_champ_frame, text="No champions in play",
                     font=("Arial", 9), bg="#fdecea", fg="#7f8c8d").pack(pady=8)
        else:
            for bc in opp_champs:
                bg = "#f9ebea" if not bc.exhausted else "#f5f5f5"
                frame = tk.Frame(self.opp_champ_frame, bg=bg, relief=tk.RIDGE, bd=1)
                frame.pack(fill=tk.X, padx=4, pady=3)

                status = "Ready" if not bc.exhausted else "Exhausted"
                guard = "Guard" if bc.guard else ""
                title = f"{bc.name}  HP {bc.current_health}/{bc.card.health}  {guard}  {status}".strip()
                tk.Label(frame, text=title, font=("Arial", 8, "bold"),
                         bg=bg, fg="#922b21", anchor="w", justify=tk.LEFT).pack(fill=tk.X, padx=4, pady=2)

                tk.Label(frame, text=self._format_effects(bc.card), font=("Arial", 7),
                         bg=bg, fg="#2c3e50", wraplength=430, anchor="w", justify=tk.LEFT).pack(fill=tk.X, padx=4)

    def _draw_hand(self):
        """Draw player hand."""
        for widget in self.hand_frame.winfo_children():
            widget.destroy()
        
        if not self.env.agent.hand:
            label = tk.Label(self.hand_frame, text="No cards in hand",
                            font=("Arial", 11), bg="white", fg="#7f8c8d")
            label.pack(pady=30)
            return
        
        # Display hand as a horizontal list
        cards_frame = tk.Frame(self.hand_frame, bg="white")
        cards_frame.pack(fill=tk.BOTH, expand=True)
        
        for card in self.env.agent.hand:
            frame = tk.Frame(cards_frame, bg="#34495e", relief=tk.RAISED, bd=2)
            frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=3, pady=10)
            
            name = tk.Label(frame, text=card.name, font=("Arial", 9, "bold"),
                           bg="#34495e", fg="white", wraplength=70)
            name.pack(padx=5, pady=5)
            
            info = f"{card.faction or 'Neutral'} | {card.card_type.title()}"
            info_label = tk.Label(frame, text=info, font=("Arial", 8),
                                 bg="#2c3e50", fg="white")
            info_label.pack(fill=tk.X, padx=5, pady=2)

            effects_label = tk.Label(frame, text=self._format_effects(card), font=("Arial", 7),
                                     bg="#34495e", fg="white", wraplength=90, justify=tk.LEFT)
            effects_label.pack(padx=5, pady=3)

    def _expend_champion(self, champion):
        """Expend a single ready champion from the player's board."""
        if not self.env or self.game_over:
            return
        if expend_champion(self.env.agent, champion, self.env.opponent):
            self.status_label.config(text=f"Used champion: {champion.name}")
            self._update_display()
        else:
            self.status_label.config(text=f"Cannot expend {champion.name} right now")

    def _buy_card(self, market_idx):
        """Buy a card from market."""
        if market_idx == 5:
            if self.env.agent.gold >= 2 and self.env.market.can_buy_fire_gem():
                if buy_card(self.env.agent, self.env.market, market_idx):
                    self.status_label.config(text="✓ Bought: Fire Gem")
                    self._update_display()
            else:
                self.status_label.config(text="✗ Cannot afford Fire Gem (need 2 gold)")
        else:
            card = self.env.market.row[market_idx]
            if not card:
                return

            if card.cost <= self.env.agent.gold:
                buy_card(self.env.agent, self.env.market, market_idx)
                self.status_label.config(text=f"✓ Bought: {card.name}")
                self._update_display()
            else:
                self.status_label.config(text=f"✗ Cannot afford {card.name} (need {card.cost} gold)")

    def _end_turn(self):
        """End turn - run opponent's turn."""
        try:
            # Pass action (action 6)
            obs, reward, done, truncated, info = self.env.step(6)
            
            if done or truncated:
                if self.env.winner == self.env.agent.name:
                    self._game_over("🎉 VICTORY! You defeated your opponent!")
                else:
                    self._game_over("💀 DEFEAT! Your opponent won.")
            else:
                self._update_display()
                self.status_label.config(text="Opponent's turn complete. Your turn to buy and play!")
        except Exception as e:
            messagebox.showerror("Error", f"Error during turn: {str(e)}")

    def _game_over(self, message):
        """Handle game over."""
        self.game_over = True
        self.end_turn_btn.config(state=tk.DISABLED)
        self.start_btn.config(state=tk.NORMAL)
        self.status_label.config(text=message)
        messagebox.showinfo("Game Over", message + "\n\nClick 'Start Game' to play again")


def main():
    root = tk.Tk()
    gui = HeroRealmsGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
