# -*- coding: utf-8 -*-
"""由用户的 spike.c 生成两个仿真用固件：
   spike_sim.c  —— 交互版
   spike_demo.c —— 演示版（上电 3 秒后自动“长按”S2 满 4 秒）

现在的 spike.c 已经自己用上了「位选低有效 pos_tab」和「LED 低电平亮 LED_ON=0x00」，
和仿真电路的接法一致，所以交互版就是原样复制；只有当用户回退到
“1=亮 / 1<<scan 高有效”的老写法时，才自动补两处硬件适配（取反）。
"""
import re

SRC = r"C:\Keil_v5\LED花样流水灯\spike.c"
src = open(SRC, encoding="utf-8").read()


def adapt(text, demo):
    # --- 只在用户代码还是“高有效”写法时才适配 ---
    if "P0 = (uchar)(1 << scan);" in text:
        print("bit-select: 需要取反（老写法）")
        text = text.replace("    P0 = (uchar)(1 << scan);\n",
                            "    P0 = (uchar)~(1 << scan);   /* 仿真适配：共阴位选低有效 */\n")
    else:
        print("bit-select: 代码已是低有效，无需适配")

    if "LED_ON      0x00" in text:
        print("LED: 代码已是低电平亮，无需适配")
    else:
        print("LED: 需要取反（老写法）")
        text, n = re.subn(r"P1\s*=\s*(0x00|0xFF|\(uchar\)[^;]+|led_val|LED_OFF);",
                          r"P1_OUT(\1);", text)
        print("  P1 writes rewritten:", n)
        anchor = "sbit BIT_LE  = P2^6;\n"
        if anchor in text:
            text = text.replace(anchor, anchor +
                                "\n/* 仿真适配：仿真里 LED 低电平点亮，P1 写入前取反 */\n"
                                "#define P1_OUT(v)  P1 = (uchar)~(v)\n")

    if demo:
        glob = "bit   flag_split = 0;      /* 充能中断请求 */\n"
        assert text.count(glob) == 1, "找不到 flag_split 声明"
        text = text.replace(glob, glob + "bit   demo_hold = 0;       /* 演示版：模拟按住下包键 */\n")

        n_k = text.count("if (K_PLANT == 0) {")
        assert n_k == 3, "K_PLANT 判断处数量不对：%d" % n_k
        text = text.replace("if (K_PLANT == 0) {", "if (K_PLANT == 0 || demo_hold) {")

        anchor2 = "    EA  = 1;\n"
        assert text.count(anchor2) == 1, "找不到 EA = 1"
        text = text.replace(anchor2, anchor2 + """
    /* ===== 演示版：上电 3 秒后自动“长按”S2，直接演示 4 秒充能 ===== */
    delay_ms(3000);
    if (state == ST_IDLE) {
        charge_ms = 0; charge_tick = 0; light_cnt = 0;
        beep_left = 0; beep_gap = 0; beep_seq = 0;
        disp_off();
        demo_hold = 1;
        state = ST_CHARGING;
    }
""")

        old3 = "                flag_plant = 0;\n                start_plant();\n"
        assert text.count(old3) == 1, "找不到 flag_plant 处理"
        text = text.replace(old3,
                            "                flag_plant = 0;\n                demo_hold = 0;      /* 松开模拟按键 */\n                start_plant();\n")

        text = text.replace(" *   —— 长按4秒充能下包（官方时间）+ 45.00 精密倒计时",
                            " *   —— 长按4秒充能下包 + 45.00 精密倒计时（SimulIDE 演示版）")
    return text


open(r"C:\Keil_v5\Spike_sim\spike_sim.c", "w", encoding="utf-8", newline="\n").write(adapt(src, False))
print("written spike_sim.c（只此一份：长按 S2 满 4 秒才启动，没有自动下包）")
