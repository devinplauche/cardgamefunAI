import { eq } from "drizzle-orm";
import { getChatGPTUser } from "@/app/chatgpt-auth";
import { getDb } from "@/db";
import { savedGames } from "@/db/schema";

export const dynamic = "force-dynamic";

async function currentUser() {
  const user = await getChatGPTUser();
  if (!user) return null;
  return user;
}

export async function GET() {
  const user = await currentUser();
  if (!user)
    return Response.json({ error: "Sign in required" }, { status: 401 });

  const [savedGame] = await getDb()
    .select()
    .from(savedGames)
    .where(eq(savedGames.userId, user.userId))
    .limit(1);

  if (!savedGame) return Response.json({ game: null });

  return Response.json({
    game: JSON.parse(savedGame.gameState),
    updatedAt: savedGame.updatedAt,
  });
}

export async function POST(request: Request) {
  const user = await currentUser();
  if (!user)
    return Response.json({ error: "Sign in required" }, { status: 401 });

  const payload = (await request.json()) as { game?: unknown };
  if (!payload.game || typeof payload.game !== "object")
    return Response.json({ error: "A game is required" }, { status: 400 });

  const gameState = JSON.stringify(payload.game);
  if (gameState.length > 100_000)
    return Response.json({ error: "Saved game is too large" }, { status: 413 });

  const updatedAt = new Date().toISOString();
  await getDb()
    .insert(savedGames)
    .values({ userId: user.userId, gameState, updatedAt })
    .onConflictDoUpdate({
      target: savedGames.userId,
      set: { gameState, updatedAt },
    });

  return Response.json({ updatedAt });
}
