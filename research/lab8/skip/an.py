import json, sys, collections, statistics as st
rows = json.load(open(sys.argv[1]))
print("time span:", min(r["timestamp"] for r in rows), "->", max(r["timestamp"] for r in rows), "hours", round((max(r["timestamp"] for r in rows)-min(r["timestamp"] for r in rows))/3600,1))
print("sides", collections.Counter(r["side"] for r in rows), "outcomes", collections.Counter(r["outcome"] for r in rows))
print("slug families", collections.Counter(r["slug"].rsplit("-",1)[0] for r in rows).most_common(5))
sizes=[r["size"] for r in rows]; prices=[r["price"] for r in rows]
print("size median", st.median(sizes), "mean", round(st.mean(sizes),2), "max", max(sizes))
print("price buckets", collections.Counter(round(p,1) for p in prices).most_common(11))
into=[r["timestamp"]-int(r["slug"].rsplit("-",1)[1]) for r in rows if r["slug"].startswith("btc-updown-5m")]
print("seconds into 5-min window: buckets of 30s", sorted(collections.Counter(min(x//30,10) for x in into).items()))
mk=collections.defaultdict(lambda: {"Up":[0,0.0],"Down":[0,0.0],"sells":0})
for r in rows:
    m=mk[r["slug"]]
    if r["side"]=="BUY": m[r["outcome"]][0]+=r["size"]; m[r["outcome"]][1]+=r["size"]*r["price"]
    else: m["sells"]+=1
both=[(s,m) for s,m in mk.items() if m["Up"][0]>0 and m["Down"][0]>0]
print("markets", len(mk), "markets where it bought BOTH sides:", len(both))
pair_cost=[]
for s,m in both:
    au=m["Up"][1]/m["Up"][0]; ad=m["Down"][1]/m["Down"][0]; pair_cost.append(au+ad)
if pair_cost: print("avg price Up+Down per pair: median", round(st.median(pair_cost),3), "share of markets with pair<1:", round(sum(p<1 for p in pair_cost)/len(pair_cost),3))
imb=[abs(m["Up"][0]-m["Down"][0])/max(m["Up"][0]+m["Down"][0],1e-9) for s,m in both]
print("share imbalance median", round(st.median(imb),3))
ex=sorted(both, key=lambda kv: -(kv[1]['Up'][0]+kv[1]['Down'][0]))[:3]
for s,m in ex: print(s, {k:(round(v[0],1),round(v[1],2)) if isinstance(v,list) else v for k,v in m.items()})
