# How to Run and Play

This document provides instructions on how to set up and play the card game.

## How to Run

1.  **Prerequisites:**
    *   You must have Python 3 installed on your system.

2.  **Running the Game:**
    *   Open a terminal or command prompt.
    *   Navigate to the root directory of the project.
    *   Run the following command:
        ```bash
        python src/ui.py
        ```
    *   This will launch the game window.

## Game Objective

The goal of the game is to reduce your opponent's health (HP) to zero. You and the AI opponent take turns playing cards to attack each other and defend.

## How to Play

*   **The Game Window:**
    *   The top section of the window displays the opponent's information, including their name, hand (shown as card backs), deck count, and HP.
    *   The bottom section displays your information, including your name, your hand of playable cards, your deck count, and your discard pile count.
    *   The center area is the play area where cards are placed when played.

*   **Taking Your Turn:**
    *   Your hand of cards is displayed at the bottom of the screen.
    *   To play a card, click the "Play" button below the card you want to play.
    *   The card's effect will be applied. For example, playing a "Strike" card will damage the opponent.

*   **AI's Turn:**
    *   Click the "AI Turn" button to let the AI take its turn. The AI will choose and play a card from its hand.

*   **Game Actions:**
    *   **Load Sample Deck:** This button will load a predefined set of cards from `data/cards.json` into your deck.
    *   **AI Turn:** This button triggers the AI's turn.

*   **Winning the Game:**
    *   You win by reducing the opponent's HP to 0 or less.
    *   You lose if your HP is reduced to 0 or less.
