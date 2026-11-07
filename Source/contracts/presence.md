# Presence contract (Workstream C)

Transport: TCP, newline-delimited JSON (one object per line, UTF-8). Default port 47800.

## Client -> Host
| type | fields | notes |
|---|---|---|
| hello | player_id, name, version | first message; host replies `welcome` |
| hover | game | sent by client only after 1 s dwell |
| hover_end | | |
| launch | game | sent by game exe process watcher |
| exit | game | |
| heartbeat | | every 5 s |
| subscribe_players | | host dashboard only |

## Host -> Client
| type | fields |
|---|---|
| welcome | server_time, heartbeat_s (5), timeout_s (15) |
| counts | games: {game_id: {hovering:int, playing:int}}, players:int |
| players | list of {player_id,name,state,game}; only to clients that sent `subscribe_players` |

Player state: `browsing` | `hovering` (+game) | `playing` (+game).
Host drops a player after 15 s with no message. Counts are rebroadcast on change, coalesced (~50 ms).
Accept (F5): 10 clients hover one game -> all see hovering=10 within 1 s.
