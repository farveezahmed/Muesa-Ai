import anthropic
import os

def call_claude_ai(symbol, timeframe, score):
    """
    The High-Performance AI Judge.
    Uses Claude 3.5 Haiku to verify institutional patterns.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("⚠️ Claude API Key missing in Railway Variables!")
        return score

    client = anthropic.Anthropic(api_key=api_key)
    
    # We ask Claude to be the 'Final Judge'
    prompt = (
        f"Analyze {symbol} on the {timeframe} chart. Current Math Score: {score}. "
        "Look for: 1. Liquidity Traps 2. Institutional Accumulation 3. RSI Divergence. "
        "Is this a high-probability trade? Reply with ONLY a number between 0 and 20 "
        "to add to the score. 0 = Dangerous/Trap, 20 = Perfect Institutional Alignment."
    )

    try:
        # Using 3.5 Haiku for the best balance of cost and speed
        response = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}]
        )
        
        # Extract the number from Claude's response
        ai_points = int(''.join(filter(str.isdigit, response.content[0].text)))
        print(f"🤖 Claude Analysis for {symbol}: +{ai_points} points")
        return score + ai_points

    except Exception as e:
        print(f"❌ Claude API Error: {e}")
        return score # If API fails, we fall back to the math score only
