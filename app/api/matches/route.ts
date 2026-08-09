import { desc } from "drizzle-orm";
import { getDb } from "@/db";
import { matchResults } from "@/db/schema";

export const dynamic = "force-dynamic";

export async function GET() {
  const matches = await getDb()
    .select()
    .from(matchResults)
    .orderBy(desc(matchResults.playedAt))
    .limit(12);
  return Response.json({ matches });
}

export async function POST(request: Request) {
  const body = (await request.json()) as Record<string, unknown>;
  const playerName =
    typeof body.playerName === "string" ? body.playerName.trim() : "";
  const winnerName =
    typeof body.winnerName === "string" ? body.winnerName.trim() : "";
  const playerScore = Number(body.playerScore);
  const winnerScore = Number(body.winnerScore);
  const playerCount = Number(body.playerCount);
  const botLevel = typeof body.botLevel === "string" ? body.botLevel : "mixed";
  if (
    !playerName ||
    !winnerName ||
    playerName.length > 24 ||
    winnerName.length > 24
  )
    return Response.json({ error: "Invalid match names" }, { status: 400 });
  if (!Number.isInteger(playerScore) || !Number.isInteger(winnerScore))
    return Response.json({ error: "Invalid scores" }, { status: 400 });
  if (!Number.isInteger(playerCount) || playerCount < 2 || playerCount > 6)
    return Response.json({ error: "Invalid player count" }, { status: 400 });
  const match = {
    id: crypto.randomUUID(),
    playerName,
    playerScore,
    winnerName,
    winnerScore,
    playerCount,
    botLevel: botLevel.slice(0, 12),
    playedAt: new Date().toISOString(),
  };
  await getDb().insert(matchResults).values(match);
  return Response.json({ match }, { status: 201 });
}
