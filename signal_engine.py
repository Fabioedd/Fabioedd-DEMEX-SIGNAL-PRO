"""Configurable, read-only technical signal engine. Confidence is a confluence score, not win probability."""
from __future__ import annotations
import importlib.util
import math
from pathlib import Path
from typing import Any

def ema(values, period):
    if len(values) < period: return None
    alpha=2/(period+1); out=sum(values[:period])/period
    for v in values[period:]: out=alpha*v+(1-alpha)*out
    return out

def rsi(values, period=14):
    if len(values) <= period: return None
    gains=[]; losses=[]
    for a,b in zip(values[-period-1:-1], values[-period:]):
        d=b-a; gains.append(max(d,0)); losses.append(max(-d,0))
    avg_g=sum(gains)/period; avg_l=sum(losses)/period
    if avg_l==0: return 100.0
    return 100-100/(1+avg_g/avg_l)

def macd(values, fast=5, slow=25, signal=5):
    if len(values) < slow+signal: return None
    # Calculate EMA series so MACD signal line is based on the full series.
    def series(period):
        alpha=2/(period+1); out=[sum(values[:period])/period]
        for v in values[period:]: out.append(alpha*v+(1-alpha)*out[-1])
        return out
    f=series(fast); s=series(slow); offset=slow-fast
    line=[f[i+offset]-s[i] for i in range(len(s))]
    sig=ema(line,signal)
    return None if sig is None else line[-1]-sig

def pattern_direction(candles, pattern):
    if len(candles)<2: return None
    c=candles[-1]; p=candles[-2]
    o,h,l,cl=(float(c[k]) for k in ("open","high","low","close"))
    po,ph,pl,pc=(float(p[k]) for k in ("open","high","low","close"))
    body=abs(cl-o); rng=max(h-l,1e-12); upper=h-max(o,cl); lower=min(o,cl)-l
    if pattern=="command_candle":
        if abs(o-l)<=rng*0.0005 and cl>o: return "CALL"
        if abs(h-o)<=rng*0.0005 and cl<o: return "PUT"
    elif pattern=="engulfing":
        if cl>o and pc<po and o<=pc and cl>=po: return "CALL"
        if cl<o and pc>po and o>=pc and cl<=po: return "PUT"
    elif pattern=="doji" and body/rng<=0.10:
        return "CALL" if lower>upper*1.3 else "PUT" if upper>lower*1.3 else None
    elif pattern=="hammer":
        if lower>=body*2 and upper<=max(body,1e-12)*0.5: return "CALL"
        if upper>=body*2 and lower<=max(body,1e-12)*0.5: return "PUT"
    return None

def custom_script_signal(path, candles, config):
    file=Path(path)
    if not file.is_file(): raise FileNotFoundError(f"Script personalizado não encontrado: {file}")
    spec=importlib.util.spec_from_file_location("demex_custom_strategy", file)
    if not spec or not spec.loader: raise ImportError("Não foi possível carregar o script personalizado.")
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    fn=getattr(module,"get_signal",None)
    if not callable(fn): raise ValueError("O script personalizado deve implementar get_signal(candles, config).")
    result=fn(candles,config)
    return result if result in ("CALL","PUT") else None

def analyze(candles, config):
    if len(candles)<30: return None
    closes=[float(c["close"]) for c in candles]
    votes=[]; reasons=[]
    if config.get("strategy_mode")=="custom_script":
        direction=custom_script_signal(config.get("custom_script_path","strategies/my_strategy.py"),candles,config)
        if not direction: return None
        votes.append(direction); reasons.append("SCRIPT PERSONALIZADO")
    else:
        inds=config.get("indicators",{})
        fast_cfg=inds.get("ema_fast",{})
        slow_cfg=inds.get("ema_slow",{})
        if fast_cfg.get("enabled") and slow_cfg.get("enabled"):
            a=ema(closes,int(fast_cfg.get("period",9))); b=ema(closes,int(slow_cfg.get("period",21)))
            if a is not None and b is not None and a!=b:
                votes.append("CALL" if a>b else "PUT"); reasons.append("EMA")
        rc=inds.get("rsi",{})
        if rc.get("enabled"):
            value=rsi(closes,int(rc.get("period",9)))
            if value is not None:
                if value<=float(rc.get("oversold",30)): votes.append("CALL"); reasons.append("RSI")
                elif value>=float(rc.get("overbought",70)): votes.append("PUT"); reasons.append("RSI")
        mc=inds.get("macd",{})
        if mc.get("enabled"):
            value=macd(closes,int(mc.get("fast",5)),int(mc.get("slow",25)),int(mc.get("signal",5)))
            if value is not None and value!=0:
                votes.append("CALL" if value>0 else "PUT"); reasons.append("MACD")
        for name in config.get("enabled_patterns",[]):
            direction=pattern_direction(candles,name)
            if direction: votes.append(direction); reasons.append("PADRÃO:"+name)
    if not votes: return None
    calls=votes.count("CALL"); puts=votes.count("PUT")
    if calls==puts: return None
    direction="CALL" if calls>puts else "PUT"
    agreeing=max(calls,puts); total=len(votes)
    confidence=round(100*agreeing/total)
    # Require at least 70% agreement; do not label this as probability of winning.
    if confidence < int(config.get("minimum_confidence",70)): return None
    return {"direction":direction,"confidence":confidence,"reasons":sorted(set(reasons)),"votes":total}
