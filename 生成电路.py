# -*- coding: utf-8 -*-
"""
用代码生成 SimulIDE 电路工程（Spike 爆能器 8051 仿真）
对应固件：spike_sim.c / spike_sim.hex（纯原 spike.c，仅把位选自 1<<scan 改为 ~(1<<scan)）

接线（与 spike.c 头注释一致）：
  P1.0~P1.7 : 8 个 LED，低电平点亮（5V-220Ω-LED-引脚）
  P2.3      : 蜂鸣器，低电平响
  P0        : 数码管段码数据总线，经 74HC573(段选，LE=P2.7) 锁存
  P2.6      : 74HC573(位选) 的 LE
  P3.1/P3.2 : 下包键 S2 / 拆包键 S3，按下接地
"""

import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
SIM_FILE = os.path.join(OUT_DIR, "Spike_sim.sim1")

# ---------------- MCU 引脚偏移（来自 data/MCS51/MCS51.package） ----------------
MCS_PIN = {
    "P10": (-8, 8), "P11": (-8, 16), "P12": (-8, 24), "P13": (-8, 32),
    "P14": (-8, 40), "P15": (-8, 48), "P16": (-8, 56), "P17": (-8, 64),
    "RST": (-8, 72),
    "P30": (-8, 80), "P31": (-8, 88), "P32": (-8, 96), "P33": (-8, 104),
    "VCC": (56, 8),
    "P00": (56, 16), "P01": (56, 24), "P02": (56, 32), "P03": (56, 40),
    "P04": (56, 48), "P05": (56, 56), "P06": (56, 64), "P07": (56, 72),
    "EA": (56, 80),
    "P27": (56, 104), "P26": (56, 112),
    "P23": (56, 136),
}

MCU_POS = (-1000, -500)
# MCU 的 io 引脚名（.sim1 里的引用方式）
def mcu_io(pkg_pin):
    if pkg_pin == "EA":
        return "PORTEEA"
    if pkg_pin == "RST":
        return "RST"
    return "PORT" + pkg_pin[1:]


def mcu_xy(pkg_pin):
    dx, dy = MCS_PIN[pkg_pin]
    return (MCU_POS[0] + dx, MCU_POS[1] + dy)


items = []
conns = []
_cid = [0]


def add_item(text):
    items.append(text)


def conn(a, b, pts):
    _cid[0] += 1
    s = ",".join("%g" % v for v in pts)
    conns.append(
        '<item itemtype="Connector" uid="connector-%d" startpinid="%s" endpinid="%s" pointList="%s" />'
        % (_cid[0], a, b, s)
    )


def p(x, y):
    return "%g,%g" % (x, y)


# ---------------- MCU ----------------
add_item(
    '<item itemtype="MCU" CircId="8051-1" mainComp="false" Show_id="true" Show_Val="false" '
    'Pos="%s" rotation="0" hflip="1" vflip="1" label="AT89S51" idLabPos="0,-20" labelrot="0" '
    'valLabPos="-16,20" valLabRot="0" Frequency="11.0592 MHz" Program="spike_sim.hex" '
    'Auto_Load="false" SerialMon="-1" />' % p(*MCU_POS)
)

# ---------------- 8 个 LED（P1.0~P1.7，低电平点亮） ----------------
# 8051 的 P1 只能弱上拉（几十 uA），直接点亮 LED 是点不亮的（SimulIDE 里 Led 带
# Grounded="true" 更会把引脚钳到 0V）。所以按真实硬件的接法：+5V -> 220Ω 限流电阻
# -> LED 阳极，LED 阴极 -> P1.x，引脚输出 0 时灌电流点亮。
LED_POS = (-1250, -540)   # x, 起始 y（Led 本体高约 16，间距 8 会糊成一坨）
LED_STEP = 24
for i in range(8):
    x = LED_POS[0]
    y = LED_POS[1] + LED_STEP * i
    py = mcu_xy("P1%d" % i)[1]
    rx = x - 40
    ch = -1240 + 10 * i        # 每根线自己的竖直通道，避免叠线
    # LED：rotation=0 -> lPin(阳极) 在左，rPin(阴极) 在右
    add_item(
        '<item itemtype="Led" CircId="Led-%d" mainComp="false" Show_id="true" Show_Val="false" '
        'Pos="%s" rotation="0" hflip="1" vflip="1" label="LED%d" idLabPos="-16,-24" labelrot="0" '
        'valLabPos="0,0" valLabRot="0" Color="Red" Grounded="false" Threshold="2.4 V" '
        'MaxCurrent="0.03 A" Resistance="0.6 Ω" />' % (i + 1, p(x, y), i + 1)
    )
    add_item(
        '<item itemtype="Resistor" CircId="Resistor-%d" mainComp="false" ShowProp="Resistance" '
        'Show_id="false" Show_Val="true" Pos="%s" rotation="0" hflip="1" vflip="1" label="R%d" '
        'idLabPos="-12,-20" labelrot="0" valLabPos="-10.9873,-16.115" valLabRot="0" '
        'Resistance="220 Ω" />' % (i + 1, p(rx, y), i + 1)
    )
    add_item('<item itemtype="Rail" CircId="Rail-%d" mainComp="false" ShowProp="Voltage" '
             'Show_id="false" Show_Val="true" Pos="%s" rotation="90" hflip="1" vflip="1" label="5V" '
             'idLabPos="-5,-10" labelrot="-90" valLabPos="-12,6" valLabRot="-90" Voltage="5 V" />'
             % (i + 2, p(rx - 20, y - 16)))
    # MCU 引脚 -> 走线通道 -> LED 阴极（低电平点亮）
    conn("8051-1-%s" % mcu_io("P1%d" % i), "Led-%d-rPin" % (i + 1),
         [mcu_xy("P1%d" % i)[0], py, ch, py, ch, y, x + 16, y])
    # 限流电阻 -> LED 阳极
    conn("Resistor-%d-rPin" % (i + 1), "Led-%d-lPin" % (i + 1), [rx + 16, y, x - 16, y])
    # 5V 母线 -> 限流电阻
    conn("Rail-%d-outnod" % (i + 2), "Resistor-%d-lPin" % (i + 1), [rx - 20, y, rx - 16, y])

# ---------------- 两个按键（S2=P3.1 下包，S3=P3.2 拆包） ----------------
add_item(
    '<item itemtype="Push" CircId="Push-1" mainComp="false" Show_id="true" Show_Val="false" '
    'Pos="-1150,-404" rotation="180" hflip="1" vflip="1" label="S2 下包" idLabPos="6,24" '
    'labelrot="90" valLabPos="-16,20" valLabRot="0" Norm_Close="false" Poles="1" />'
)
add_item(
    '<item itemtype="Push" CircId="Push-2" mainComp="false" Show_id="true" Show_Val="false" '
    'Pos="-1150,-352" rotation="180" hflip="1" vflip="1" label="S3 拆包" idLabPos="6,24" '
    'labelrot="90" valLabPos="-16,20" valLabRot="0" Norm_Close="false" Poles="1" />'
)
# S2(下包) -> P3.3 / INT1
conn("Push-1-pinP0", "8051-1-PORT33", [-1134, -404, -1085, -404, -1085, -412,
                                       mcu_xy("P33")[0], -412])
# S3(拆包) -> P3.2 / INT0
conn("Push-2-pinP0", "8051-1-PORT32", [-1134, -352, -1060, -352, -1060, -404,
                                       mcu_xy("P32")[0], -404])
# 按键接地
add_item('<item itemtype="Ground" CircId="Ground-1" mainComp="false" Show_id="false" Show_Val="false" '
         'Pos="-1200,-404" rotation="0" hflip="1" vflip="1" label="GND" idLabPos="-16,8" labelrot="0" '
         'valLabPos="0,0" valLabRot="0" />')
conn("Push-1-switch0pinN", "Ground-1-Gnd", [-1166, -404, -1200, -404, -1200, -420])
add_item('<item itemtype="Ground" CircId="Ground-2" mainComp="false" Show_id="false" Show_Val="false" '
         'Pos="-1230,-352" rotation="0" hflip="1" vflip="1" label="GND" idLabPos="-16,8" labelrot="0" '
         'valLabPos="0,0" valLabRot="0" />')
conn("Push-2-switch0pinN", "Ground-2-Gnd", [-1166, -352, -1230, -352, -1230, -368])

# ---------------- 蜂鸣器（P2.3 低电平响） ----------------
add_item(
    '<item itemtype="AudioOut" CircId="AudioOut-1" mainComp="false" Show_id="true" Show_Val="false" '
    'Pos="-700,-330" rotation="0" hflip="-1" vflip="1" label="BZ1 蜂鸣器" idLabPos="-20,-36" '
    'labelrot="0" valLabPos="0,0" valLabRot="0" Buzzer="true" Impedance="8 Ω" />'
)
conn("AudioOut-1-lPin", "8051-1-PORT23", [-684, -338, -760, -338, -760, -364, mcu_xy("P23")[0], -364])
add_item('<item itemtype="Fixed Voltage" CircId="Fixed Voltage-1" mainComp="false" Show_id="false" '
         'Show_Val="true" Pos="-664,-330" rotation="0" hflip="1" vflip="1" label="+5V" '
         'idLabPos="-64,-24" labelrot="0" valLabPos="-16,8" valLabRot="0" Voltage="5 V" Out="false" />')
conn("AudioOut-1-rPin", "Fixed Voltage-1-outnod", [-684, -330, -648, -330])

# ---------------- RST 接 5V（SimulIDE 的 RST 引脚是低有效 !rst，接地=一直复位） ----------------
add_item('<item itemtype="Fixed Voltage" CircId="Fixed Voltage-2" mainComp="false" Show_id="false" '
         'Show_Val="true" Pos="-1070,-428" rotation="0" hflip="1" vflip="1" label="+5V" '
         'idLabPos="-64,-24" labelrot="0" valLabPos="-16,8" valLabRot="0" Voltage="5 V" Out="false" />')
conn("8051-1-RST", "Fixed Voltage-2-outnod", [mcu_xy("RST")[0], -428, -1054, -428])
# ---------------- EA 接 5V 母线（Rail）----------------
# 关键：EA 必须接到 Rail，接 Fixed Voltage 会被模型读成低电平 → 选外部程序存储器 → PC 跑飞
add_item('<item itemtype="Rail" CircId="Rail-1" mainComp="false" ShowProp="Voltage" Show_id="false" '
         'Show_Val="true" Pos="-880,-420" rotation="90" hflip="1" vflip="1" label="5V Rail" '
         'idLabPos="-5,-10" labelrot="-90" valLabPos="-12,6" valLabRot="-90" Voltage="5 V" />')
conn("8051-1-PORTEEA", "Rail-1-outnod", [mcu_xy("EA")[0], -420, -882, -420, -880, -420])

# ---------------- P0 上拉排阻（P0 为开漏，必须上拉） ----------------
DIP_POS = (-900, -680)
add_item(
    '<item itemtype="ResistorDip" CircId="ResistorDip-1" mainComp="false" ShowProp="Resistance" '
    'Show_id="true" Show_Val="true" Pos="%s" rotation="0" hflip="1" vflip="1" label="P0 上拉" '
    'idLabPos="-24,-10" labelrot="0" valLabPos="4,-26" valLabRot="90" Resistance="10 kΩ" '
    'Size="8 _Resist." PullUp="true" PuVolt="5 V" />' % p(*DIP_POS)
)

# ---------------- 两片 74HC573 ----------------
L1_POS = (-830, -480)   # 段选
L2_POS = (-830, -320)   # 位选
for cid, pos, lab in ((1, L1_POS, "U1 74HC573 段选"), (2, L2_POS, "U2 74HC573 位选")):
    add_item(
        '<item itemtype="Subcircuit" CircId="74HC573-%d" mainComp="false" Show_id="true" Show_Val="false" '
        'Pos="%s" rotation="0" hflip="1" vflip="1" label="%s" idLabPos="0,-20" labelrot="0" '
        'valLabPos="-16,20" valLabRot="0" Logic_Symbol="false" />' % (cid, p(*pos), lab)
    )


def latch_pin(cid, name, pos, dy_index=None, right=False):
    """74HC573 引脚偏移：左侧 !OE(8)、D0..D7(16..72)；右侧 Vcc(8)、Q0..Q7(16..72)、IE(80)"""
    if name in ("!OE", "IE", "Vcc"):
        off = {"!OE": (-8, 8), "Vcc": (40, 8), "IE": (40, 80)}[name]
    elif name.startswith("D"):
        off = (-8, 16 + 8 * int(name[1:]))
    else:
        off = (40, 16 + 8 * int(name[1:]))
    return (pos[0] + off[0], pos[1] + off[1])


# ---------------- P0 总线：MCU -> Node -> 两片锁存器 / 上拉 ----------------
# Node 每个节点只有 3 个引脚(0..2)，4 条支路必须拆成两个串联节点
for k in range(8):
    ny = -484 + 8 * k
    na = "Node-%d" % (2 * k + 1)
    nb = "Node-%d" % (2 * k + 2)
    add_item('<item itemtype="Node" CircId="%s" mainComp="false" Pos="%s" />' % (na, p(-900, ny)))
    add_item('<item itemtype="Node" CircId="%s" mainComp="false" Pos="%s" />' % (nb, p(-886, ny)))
    # a) MCU -> NodeA
    conn("8051-1-%s" % mcu_io("P0%d" % k), na + "-0",
         [mcu_xy("P0%d" % k)[0], ny, -914, ny, -914, ny + 4, -900, ny + 4])
    # b) NodeA -> U1 Dk
    d1 = latch_pin(1, "D%d" % k, L1_POS)
    conn(na + "-1", "74HC573-1-D%d" % k, [-900, ny, -868, ny, -868, d1[1], d1[0], d1[1]])
    # c) NodeA -> NodeB（串联节点）
    conn(na + "-2", nb + "-0", [-900, ny, -886, ny])
    # d) NodeB -> U2 Dk
    d2 = latch_pin(2, "D%d" % k, L2_POS)
    conn(nb + "-1", "74HC573-2-D%d" % k, [-886, ny, -876, ny, -876, d2[1], d2[0], d2[1]])
    # e) NodeB -> 上拉排阻
    ry = DIP_POS[1] - 24 + 8 * k
    conn(nb + "-2", "ResistorDip-1-resistor%d-ePin%d" % (k, 2 * k),
         [-886, ny, -920, ny, -920, ry, -916, ry])

# ---------------- 8 位共阴数码管 ----------------
SEG_POS = (-500, -480)
add_item(
    '<item itemtype="Seven Segment" CircId="7 Segment-1" mainComp="false" Show_id="true" '
    'Show_Val="false" Pos="%s" rotation="0" hflip="1" vflip="1" label="8位数码管" '
    'idLabPos="-16,-24" labelrot="0" valLabPos="0,0" valLabRot="0" Color="Yellow" '
    'NumDisplays="8" Vertical_Pins="false" CommonCathode="true" Threshold="2.4 V" '
    'MaxCurrent="0.007 A" Resistance="1 Ω" />' % p(*SEG_POS)
)
SEG_NAMES = ["a", "b", "c", "d", "e", "f", "g"]   # dp 未接（固件不用小数点）

# 段选锁存输出 -> 各段引脚
for k in range(7):
    q = latch_pin(1, "Q%d" % k, L1_POS)
    sx = SEG_POS[0] - 24
    sy = SEG_POS[1] - 24 + 8 * k
    conn("74HC573-1-Q%d" % k, "7 Segment-1-pin_%s" % SEG_NAMES[k],
         [q[0], q[1], -760, q[1], -760, sy, sx, sy])

# 位选锁存输出 -> 各位的公共极（低电平点亮）
for k in range(8):
    q = latch_pin(2, "Q%d" % k, L2_POS)
    cx = SEG_POS[0] + 8 + 32 * k
    cy = SEG_POS[1] + 32
    conn("74HC573-2-Q%d" % k, "7 Segment-1-pin_common%s" % "abcdefgh"[k],
         [q[0], q[1], -770, q[1], -770, -430, cx, -430, cx, cy])

# ---------------- 锁存器控制脚 ----------------
# U1 LE = P2.6（段选 DU，对应固件 sbit DU = P2^6）
conn("8051-1-PORT26", "74HC573-1-IE", [mcu_xy("P26")[0], -388, -820, -388, -820, -400, -790, -400])
# U2 LE = P2.7（位选 WE，对应固件 sbit WE = P2^7）
conn("8051-1-PORT27", "74HC573-2-IE", [mcu_xy("P27")[0], -396, -908, -396, -908, -240, -790, -240])
# 两片 !OE 接地（输出使能）
add_item('<item itemtype="Ground" CircId="Ground-3" mainComp="false" Show_id="false" Show_Val="false" '
         'Pos="-838,-520" rotation="0" hflip="1" vflip="1" label="GND" idLabPos="-16,8" labelrot="0" '
         'valLabPos="0,0" valLabRot="0" />')
conn("74HC573-1-!OE", "Ground-3-Gnd", [-838, -472, -838, -536])
add_item('<item itemtype="Ground" CircId="Ground-4" mainComp="false" Show_id="false" Show_Val="false" '
         'Pos="-838,-280" rotation="0" hflip="1" vflip="1" label="GND" idLabPos="-16,8" labelrot="0" '
         'valLabPos="0,0" valLabRot="0" />')
conn("74HC573-2-!OE", "Ground-4-Gnd", [-838, -312, -838, -296])

# ---------------- 5V 供电：两片 573 的 Vcc + MCU 的 Vcc ----------------
# 573 是 CMOS 器件，Vcc 悬空时输出全是高阻，数码管不会亮
add_item('<item itemtype="Fixed Voltage" CircId="Fixed Voltage-4" mainComp="false" Show_id="false" '
         'Show_Val="true" Pos="-700,-580" rotation="0" hflip="1" vflip="1" label="+5V" '
         'idLabPos="-64,-24" labelrot="0" valLabPos="-16,8" valLabRot="0" Voltage="5 V" Out="false" />')
# 573 的 Vcc 走节点扇出（Node 只有 3 个引脚，两片需要串两级）
add_item('<item itemtype="Node" CircId="Node-17" mainComp="false" Pos="-660,-580" />')
add_item('<item itemtype="Node" CircId="Node-18" mainComp="false" Pos="-660,-596" />')
conn("Fixed Voltage-4-outnod", "Node-17-0", [-684, -580, -660, -580])
conn("Node-17-1", "74HC573-1-Vcc", [-660, -580, -660, -472, -790, -472])
conn("Node-17-2", "Node-18-0", [-660, -580, -660, -596])
conn("Node-18-1", "74HC573-2-Vcc", [-660, -596, -660, -312, -790, -312])
conn("Node-18-2", "8051-1-VCC", [-660, -596, -600, -596, -600, -492, -944, -492])

# ---------------- 输出 ----------------
import re as _re

OFF = (1500, 900)   # 整体平移，保证坐标为正值，打开工程就在视野内


def _shift_item(line):
    m = _re.search(r'Pos="(-?[\d.]+),(-?[\d.]+)"', line)
    if not m:
        return line
    x = float(m.group(1)) + OFF[0]
    y = float(m.group(2)) + OFF[1]
    return line[:m.start()] + 'Pos="%g,%g"' % (x, y) + line[m.end():]


def _shift_pts(line):
    m = _re.search(r'pointList="([^"]*)"', line)
    if not m:
        return line
    vals = [float(v) for v in m.group(1).split(",")]
    vals = [v + (OFF[0] if i % 2 == 0 else OFF[1]) for i, v in enumerate(vals)]
    return line[:m.start()] + 'pointList="%s"' % ",".join("%g" % v for v in vals) + line[m.end():]


items = [_shift_item(x) for x in items]
conns = [_shift_pts(x) for x in conns]

lines = ['<circuit version="" rev="2224" stepSize="1000000" stepsPS="1000000" NLsteps="100000" '
         'reaStep="1000000" animate="1" >', ""]
lines += items + [""] + conns + ["", "</circuit>", ""]
with open(SIM_FILE, "w", encoding="utf-8", newline="\n") as f:
    f.write("\n".join(lines))
print("OK ->", SIM_FILE, " items=", len(items), " connectors=", len(conns))
