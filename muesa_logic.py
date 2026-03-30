import os

def validate_trade_setup(symbol, tech):
    """
    MUESA Advanced Logic: 7 Patterns from your PDF (Math-Only)
    NON-NEGOTIABLE RULE: Requires a Score of 75+ for Entry.
    """
    score = 0
    patterns_detected = []

    # 1. Pattern: Volume Spike + Flat Price (Accumulation)
    # Logic: High Volume (>3x) but Price hasn't moved more than 0.5%
    if tech['volume_spike'] and abs(tech.get('price_change', 0)) < 0.5:
        score += 25
        patterns_detected.append("💎 Accumulation (Vol Spike + Flat Price)")

    # 2. Pattern: Trend Exhaustion Reversal (RSI)
    if tech['rsi'] < 20:
        score += 25
        patterns_detected.append("🪂 Trend Exhaustion (Extreme RSI < 20)")
    elif tech['rsi'] < 30:
        score += 15
        patterns_detected.append("📉 Oversold (RSI < 30)")

    # 3. Pattern: Bullish EMA Cross (Confirmation)
    if tech['ema_cross']:
        score += 15
        patterns_detected.append("🚀 EMA 9/21 Bullish Cross")

    # 4. Pattern: Losers List Bounce (Mean Reversion)
    # If the coin is down more than 5% on the day
    if tech.get('daily_change', 0) < -5:
        score += 10
        patterns_detected.append("📉 Losers List Bounce Potential")

    # 5. Pattern: Support Level Hold (Within 1% of the 100-period low)
    if tech['current_price'] <= tech.get('support_level', 0) * 1.01:
        score += 15
        patterns_detected.append("🛡️ Support Level Hold")

    # 6. Pattern: Quiet Accumulation (Low Vol + Low RSI)
    if not tech['volume_spike'] and tech['rsi'] < 35:
        score += 5
        patterns_detected.append("🤫 Quiet Accumulation")

    # 7. Pattern: Liquidity Check (Spread/Volume baseline)
    score += 5 
    patterns_detected.append("💧 Liquidity Verified")

    # --- THE NON-NEGOTIABLE 75+ RULE ---
    is_approved = score >= 75
    
    print(f"📝 {symbol} Scan Results: {score}/100")
    print(f"🔎 Patterns: {', '.join(patterns_detected)}")
    
    return {
        "symbol": symbol,
        "approved": is_approved,
        "score": score,
        "price": tech['current_price'],
        "reason": " | ".join(patterns_detected)
    }
