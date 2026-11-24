# -*- coding: utf-8 -*-
"""校验生成的 .sim1：XML 合法性、引脚名是否存在、同一引脚是否被重复占用"""
import re
import xml.etree.ElementTree as ET
import collections
import os

f = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Spike_sim.sim1")
raw = open(f, encoding="utf-8").read()

# 1) XML
try:
    root = ET.fromstring(raw)
except Exception as e:
    print("XML 解析失败:", e)
    raise SystemExit(1)

items = root.findall("item")
print("XML OK, item 数 =", len(items))

def pins_of(it):
    t = it.get("itemtype")
    cid = it.get("CircId")
    if t == "MCU":
        return {"PORT%02d" % (p) for p in range(4) for _ in [0]} | \
               {"PORT%d%d" % (p, b) for p in range(4) for b in range(8)} | \
               {"PORTEEA", "PORTEALE", "PORTEPSEN", "RST", "VCC", "VSS"}
    if t == "Led":
        return {"lPin", "rPin"}
    if t == "Push":
        return {"pinP0", "switch0pinN"}
    if t == "Ground":
        return {"Gnd"}
    if t == "AudioOut":
        return {"lPin", "rPin"}
    if t == "Fixed Voltage":
        return {"outnod"}
    if t == "Rail":
        return {"outnod"}
    if t == "Resistor":
        return {"lPin", "rPin"}
    if t == "ResistorDip":
        n = int(re.match(r"(\d+)", it.get("Size")).group(1))
        return {"resistor%d-ePin%d" % (r, e) for r in range(n) for e in range(2 * n)}
    if t == "Subcircuit":
        return ({"!OE", "IE", "Vcc", "Gnd"}
                | {"D%d" % i for i in range(8)}
                | {"Q%d" % i for i in range(8)})
    if t == "Seven Segment":
        return {"pin_%s" % s for s in list("abcdefg") + ["dp"]} | \
               {"pin_common%s" % c for c in "abcdefgh"}
    if t == "Node":
        return None  # 任意编号
    return set()

by_id = {}
for it in items:
    cid = it.get("CircId")
    if cid:
        by_id[cid] = it

errors = []
usage = collections.Counter()

for c in root.findall("item"):
    if c.get("itemtype") != "Connector":
        continue
    for end in ("startpinid", "endpinid"):
        pid = c.get(end)
        # 用已知元件 id 做最长前缀匹配（元件 id 本身可能含 '-'）
        cid = None
        for k in sorted(by_id, key=len, reverse=True):
            if pid.startswith(k + "-"):
                cid = k
                break
        if cid is None:
            errors.append("无法匹配元件: " + pid)
            continue
        pin = pid[len(cid) + 1:]
        it = by_id.get(cid)
        if it is None:
            errors.append("引用了不存在的元件: %s (from %s)" % (cid, pid))
            continue
        valid = pins_of(it)
        if valid is None:
            continue
        if pin not in valid:
            errors.append("引脚不存在: %s (%s 的有效引脚见下)" % (pid, it.get("itemtype")))
        usage[pid] += 1

print("connector 数 =", sum(1 for c in root.findall("item") if c.get("itemtype") == "Connector"))

# 重复占用
dup = [k for k, v in usage.items() if v > 1]
if dup:
    print("\n被重复引用的引脚:")
    for d in dup:
        print("   ", d, "×", usage[d])

if errors:
    print("\n发现问题:")
    for e in errors:
        print("   ", e)
else:
    print("\n引脚检查通过：所有引用都指向存在的引脚")

# 元件清单
print("\n元件清单:")
for it in items:
    if it.get("itemtype") == "Connector":
        continue
    print("   %-28s %-16s %s" % (it.get("CircId"), it.get("itemtype"), it.get("Pos")))
