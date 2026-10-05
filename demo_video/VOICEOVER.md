# AURORA demo video: voiceover script

Video: `demo_video/aurora_demo.mp4` (1920×1080, 30 fps, about 2:53, silent).
Read at a calm pace, about 140 words a minute. Each block starts on the time shown. If you finish a block early, pause; don't run into the next scene.
The small caption at the bottom-left of each scene tells you where you are.

---

### 0:00 · Title card: "AURORA"
This is AURORA: an offline AI energy manager for India's polar research stations, built for Smart India Hackathon problem statement 26061.

### 0:09 · Card: "The problem"
Stations like Bharati run on diesel that arrives by ship once a year. Fixed rules waste that fuel, throw away free sun and wind, and leave the station exposed to storms and late ships.

### 0:20 · Station now
This is the station right now, on a digital twin of Bharati. One screen answers three questions: is the station safe, how much fuel is left, and will it last until the ship. This flow shows where every kilowatt comes from and where it goes. Below, AURORA explains what it is doing, in plain language.

### 0:43 · Next 48 hours
Every fifteen minutes AURORA forecasts the next forty-eight hours of weather, demand, solar and wind, with uncertainty bands rather than a single guess. An optimiser then plans the generators, battery, heat storage and flexible loads together, hour by hour.

### 1:01 · Scenario: blizzard incoming
Now let's stress it. I trigger a blizzard arriving in sixteen hours. Storm Mode switches on at once. AURORA starts charging the battery and heating the thermal tank, keeps a standby generator ready, and plans to park the wind turbines before the wind gets dangerous.

### 1:23 · Why AURORA acted
Nothing here is a black box. Every decision comes with a reason card: what AURORA did, why it did it, and how much diesel it saves. A safety guardrail checks every command before it reaches the station.

### 1:35 · Scenario: generator failure
In the middle of the storm, generator G1 trips. AURORA takes it out of the plan straight away and re-plans with one fewer unit. Life-support loads are Tier 1, and Tier 1 is never cut.

### 1:50 · Scenario: ship delayed 30 days → Will fuel last?
The station leader's biggest question is whether the fuel will last until the ship. AURORA answers with a probability from a thousand simulated futures. With the ship thirty days late, that score collapses. AURORA ranks the actions that help most and tells the team when to call headquarters.

### 2:08 · A full year: AURORA vs diesel-first
Finally, a full year on real 2023 NASA weather: the same station and the same loads, AURORA against today's diesel-first rules. Watch the gap grow, day after day. The generators run far fewer hours at healthier loads, and almost no renewable energy is wasted.

### 2:31 · Card: results
Over the year, that is twenty-two and a half percent less diesel, one hundred and sixty-six tonnes of CO2 avoided, life support served one hundred percent of the time, and eighty-four extra days of fuel in reserve.

### 2:44 · Card: closing
AURORA runs fully offline: sense, predict, decide, guard, act. Every number you saw comes from our digital twin. Thank you.

---

## Recording tips
- Record the voice in one take while watching the video muted, then line it up in any editor (CapCut, iMovie, DaVinci Resolve, Clipchamp).
- If a block runs long, drop its last sentence rather than speeding up.
- To get a shorter cut, the generator-failure scene (1:35–1:50) can be removed without breaking the story.
