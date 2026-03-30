def calculate_muesa_score(market_data: dict) -> int:
    score = 0
    if market_data.get('chart_formation_valid'): score += 15
    if market_data.get('volume_3x_ma10'): score += 15
    if market_data.get('strong_support_resistance'): score += 15
    if market_data.get('funding_rate', 1.0) <= 0.1: score += 15 
    if market_data.get('open_interest_rising'): score += 10
    if market_data.get('news_sentiment_positive'): score += 10
    if market_data.get('spread_below_03'): score += 10
    if market_data.get('price_at_key_fib'): score += 10

    rsi_div = market_data.get('rsi_bullish_divergence')
    macd_cross = market_data.get('macd_crossover')

    if rsi_div and macd_cross:
        score += 15
    else:
        if rsi_div: score += 8
        if macd_cross: score += 6

    if market_data.get('price_exactly_618'): score += 5
    if market_data.get('breakout_retest'): score += 5
    if market_data.get('timeframe_aligned'): score += 10 

    return score

def calculate_trade_parameters(entry_price: float, atr: float, trade_type: str) -> dict:
    atr_buffer = atr * 0.5 
    stop_loss = entry_price - atr_buffer if trade_type == 'LONG' else entry_price + atr_buffer

    sl_distance_percent = abs((entry_price - stop_loss) / entry_price) * 100
    if sl_distance_percent > 5:
        return {"valid": False, "reason": "Coin too volatile. SL exceeds 5% limit."}

    risk_amount = abs(entry_price - stop_loss)
    target = entry_price + (risk_amount * 2) if trade_type == 'LONG' else entry_price - (risk_amount * 2)

    return {"valid": True, "stop_loss": stop_loss, "target": target}

def validate_trade_setup(coin_name: str, market_data: dict, wallet_balance: float, active_trades_count: int) -> dict:
    score = calculate_muesa_score(market_data)
    
    if score < 75: return {"approved": False, "reason": "Score below 75."}
    if not market_data.get('volume_3x_ma10'): return {"approved": False, "reason": "Volume not 3x MA10."}
    if not market_data.get('open_interest_rising'): return {"approved": False, "reason": "OI not rising."}
    if market_data.get('funding_rate', 1.0) > 0.1: return {"approved": False, "reason": "Funding rate extreme."}
    if active_trades_count >= 5: return {"approved": False, "reason": "Max 5 active trades."}

    trade_params = calculate_trade_parameters(market_data['entry_price'], market_data['atr'], market_data['trade_type'])
    if not trade_params['valid']: return {"approved": False, "reason": trade_params['reason']}

    position_size = wallet_balance * 0.25

    return {
        "approved": True, "coin": coin_name, "score": score, "allocation": position_size,
        "leverage": 5, "entry_price": market_data['entry_price'], 
        "stop_loss": trade_params['stop_loss'], "target": trade_params['target']
    }
