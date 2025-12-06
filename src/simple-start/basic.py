import tkinter as tk
from tkinter import messagebox

# Set up the main window
root = tk.Tk()
root.title("Card Game")
root.geometry("600x400")

# Add a label to display information
label = tk.Label(root, text="Welcome to the Card Game!", font=("Arial", 24))
label.pack(pady=20)

# Button to start the game
def start_game():
    messagebox.showinfo("Game Start", "The game is starting!")

start_button = tk.Button(root, text="Start Game", command=start_game, font=("Arial", 14))
start_button.pack(pady=20)

# Run the application
root.mainloop()
