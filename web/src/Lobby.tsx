import { useCallback, useEffect, useState } from 'react';
import type { GameSummary, User } from './types';
import { createGame, joinGame, listGames } from './api';

function statusLabel(status: GameSummary['status']): string {
  if (status === 'waiting') return 'Waiting for opponent';
  if (status === 'playing') return 'In progress';
  return 'Finished';
}

export function Lobby({ user, onOpenGame }: { user: User; onOpenGame: (gameId: string) => void }) {
  const [games, setGames] = useState<GameSummary[]>([]);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [newCode, setNewCode] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const payload = await listGames();
      setGames(payload.games);
      setListError(null);
    } catch (err) {
      // Don't silently show "No games yet" when the list simply failed to load.
      setListError(err instanceof Error ? err.message : 'Could not load your games.');
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      void refresh();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  async function handleCreate() {
    setError(null);
    setBusy(true);
    try {
      const created = await createGame();
      setNewCode(created.inviteCode);
      await refresh();
      onOpenGame(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create a game.');
    } finally {
      setBusy(false);
    }
  }

  async function handleJoin(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const joined = await joinGame(code.trim());
      setCode('');
      await refresh();
      onOpenGame(joined.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not join that game.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="lobby">
      <section className="lobby-actions">
        <div className="lobby-card">
          <h2>Start a match</h2>
          <p className="lobby-hint">Create a game and share the invite code with your opponent.</p>
          <button className="primary-button" onClick={() => void handleCreate()} disabled={busy}>
            Create game
          </button>
          {newCode ? (
            <p className="lobby-code">
              Invite code: <strong>{newCode}</strong>
            </p>
          ) : null}
        </div>
        <div className="lobby-card">
          <h2>Join a match</h2>
          <p className="lobby-hint">Enter the invite code your opponent shared.</p>
          <form onSubmit={handleJoin} className="lobby-join">
            <input
              className="auth-input lobby-code-input"
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              placeholder="ABC123"
              maxLength={6}
              autoComplete="off"
            />
            <button type="submit" className="primary-button" disabled={busy || code.trim().length === 0}>
              Join
            </button>
          </form>
        </div>
      </section>
      {error ? <p className="auth-error lobby-error">{error}</p> : null}
      <section className="lobby-list">
        <div className="lobby-list-head">
          <h2>Your games</h2>
          <button className="secondary-button" onClick={() => void refresh()}>
            Refresh
          </button>
        </div>
        {listError ? <p className="auth-error lobby-error">{listError}</p> : null}
        {games.length === 0 ? (
          <p className="lobby-empty">No games yet. Create one or join with an invite code.</p>
        ) : (
          <ul className="lobby-games">
            {games.map((game) => (
              <li key={game.id}>
                <button className="lobby-game" onClick={() => onOpenGame(game.id)}>
                  <span className="lobby-game-opponent">
                    {game.opponent ?? (game.status === 'waiting' ? 'Open invite' : 'Unknown')}
                  </span>
                  <span className="lobby-game-meta">
                    <span className={`lobby-status lobby-status-${game.status}`}>{statusLabel(game.status)}</span>
                    <span className="lobby-game-code">{game.inviteCode}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
