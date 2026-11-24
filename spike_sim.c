/*============================================================
 * spike.c  —  《无畏契约》爆能器（Spike）实物模拟
 * 开发板：青翔 QX-MCS51 V3.5   芯片：STC89C52RC   晶振：11.0592MHz
 * 编译器：Keil C51
 *
 * ── 硬件 ────────────────────────────────────────────────
 *   LED        P1.0~P1.7，阳极经排阻接 +5V，低电平亮（0=亮 1=灭）
 *   蜂鸣器      P2.3，经 S8550，低电平响（有源）
 *   数码管      8位共阴，P0 数据总线
 *              段选锁存 DU = P2.6，位选锁存 WE = P2.7
 *              位选低电平有效：pos[0]=0xFE 为最左，pos[7]=0x7F 为最右
 *              扫描必须先位选、后段选
 *   下包键 S2 = P3.3 / INT1（外部中断1，下降沿触发）
 *   拆包键 S3 = P3.2 / INT0（外部中断0，下降沿触发）
 *
 * ── 流程 ────────────────────────────────────────────────
 *   待机      数码管全灭、LED 全灭、蜂鸣器静音（上电即此状态）
 *
 *   充能      长按 S2 满 4 秒（Valorant 官方下包时间）
 *             8 个 LED 每 0.5 秒亮一个（P1.7 → P1.0 依次点亮）
 *             按下 0.2 秒后"嘀嘀"两声，之后灯亮不再出声
 *             中途松手 → 充能清零，回到待机
 *
 *   下包完成  LED 全亮 + 嘀一声，数码管显示 45.00
 *
 *   倒计时    滴答四档阶跃（参照游戏节奏）：
 *             剩余 45  ~ 22.5 秒 ：1000ms
 *             剩余 22.5~ 10   秒 ：500ms
 *             剩余 10  ~  5   秒 ：250ms
 *             剩余 5   ~ 0.5 秒 ：125ms
 *             剩余 0.5 ~  0   秒 ：长鸣不停
 *             每响一声 8 灯同步全亮、响完立即熄灭（心跳脉冲）
 *             最后 10 秒数码管 200ms 亮 / 200ms 灭急闪
 *
 *   拆包      长按 S3，共 7 秒（Valorant 半拆机制，3.5 秒为存档点）
 *             LED 从 P1.0 反向逐个熄灭
 *             左块 4 位数码管外框走一圈 12 段环形进度（583ms 一段）
 *             右块 4 位数码管照常显示倒计时，拆包不影响
 *             拆包期间不再有脉冲
 *             到 3.5 秒嘀一声（半拆完成，正好 6 段 = 半圈）
 *             松手进度保留在前 4 个灯 / 半圈
 *             未到 3.5 秒松手 → 进度清零
 *             再按住只需再拆 3.5 秒即完成
 *
 *   拆包成功  数码管 8 位全部亮起 → 显示 SFHS（守方获胜）
 *   爆炸      全亮急闪 + 长鸣（2 秒）→ 数码管 8 位全部亮起
 *             → 显示 GFHS（攻方获胜）
 *
 * ── 时基分工（重要）─────────────────────────────────────
 *   T0 中断（1ms）只做两件事：重装初值、捕获按键松手、给 tick1ms 加 1
 *   数码管扫描、LED PWM、倒计时运算全部放在主循环里按 tick1ms 消费
 *   这样中断占用极短，1ms 节拍不会被自身中断服务程序的耗时吃掉，
 *   仿真里的"显示时间 ≠ 运行时间"问题即由此消除
 *============================================================*/

#include <reg52.h>

#define uchar unsigned char
#define uint  unsigned int

/* ---- 引脚 ---- */
sbit BEEP     = P2^3;      /* 蜂鸣器，低电平响 */
sbit DU       = P2^6;      /* 数码管段选锁存 */
sbit WE       = P2^7;      /* 数码管位选锁存 */
sbit K_PLANT  = P3^3;      /* 下包键 S2，接 INT1 外部中断 */
sbit K_DEFUSE = P3^2;      /* 拆包键 S3，接 INT0 外部中断 */

/* ---- 状态 ---- */
#define ST_IDLE     0
#define ST_CHARGING 1
#define ST_PLANTED  2
#define ST_DEFUSED  3
#define ST_EXPLODED 4

/* ---- 参数 ---- */
#define PLANT_SEC   45          /* 倒计时秒数（Valorant 官方 45 秒） */
#define HOLD_MS     7000        /* 拆包长按 7 秒 */
#define CHARGE_MS   4000        /* 下包长按 4 秒 */
#define CHARGE_STEP 500         /* 充能每 500ms 亮一个灯（500*8=4000） */
#define DOT_POS     5           /* 小数点叠在 disp[5]（45.00 的"5"后面） */
#define LED_ON      0x00        /* 8 灯全亮（低电平有效） */
#define LED_OFF     0xFF        /* 8 灯全灭 */
#define LED_DUTY    2           /* LED 亮度 0~5，2=40%（改这个数调亮度） */
#define TICK_MAX    20          /* 待处理节拍上限，防止主循环被阻塞时计数溢出 */

/* ---- 共阴段码：0~9, 10='-', 11=空, 12='S', 13='F', 14='H', 15='G' ---- */
uchar code seg[16] = {
    0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07,
    0x7F, 0x6F, 0x40, 0x00,
    0x6D, 0x71, 0x76, 0x3D
};

/* ---- 位选码，[0]=最左 COM1，[7]=最右 COM8 ---- */
uchar code pos[8] = {0xFE, 0xFD, 0xFB, 0xF7, 0xEF, 0xDF, 0xBF, 0x7F};

/* ---- 点亮前 n 个 LED（从 P1.7 向 P1.0）：n=0 全灭，n=1 只亮 P1.7，n=8 全亮 ---- */
uchar code on_tab[9] = {0xFF, 0x7F, 0x3F, 0x1F, 0x0F, 0x07, 0x03, 0x01, 0x00};

/* ---- 拆除进度：已熄灭 ext 个（从 P1.0 反向往回退），亮 8-ext 个 ---- */
uchar code defuse_tab[9] = {0x00, 0x01, 0x03, 0x07, 0x0F, 0x1F, 0x3F, 0x7F, 0xFF};

/* ---- 左块 4 位数码管外框一圈 12 段（对应照片上标注的 1~12）
 * disp[0..3] = 左块 4 位（最左 ~ 最右）
 * 段位：a=0x01 顶横   b=0x02 右上竖   c=0x04 右下竖
 *       d=0x08 底横   e=0x10 左下竖   f=0x20 左上竖
 * 路径（顺时针一圈）：
 *   1 底横最右 -> 2 3 4 底横往左 -> 5 左下竖 -> 6 左上竖
 *   -> 7 8 9 10 顶横往右 -> 11 右上竖 -> 12 右下竖
 * 半拆 3.5 秒 = 6 段 = 正好半圈                                     ---- */
uchar code ring_pos[12] = {3, 2, 1, 0, 0, 0, 0, 1, 2, 3, 3, 3};
uchar code ring_seg[12] = {0x08, 0x08, 0x08, 0x08, 0x10, 0x20,
                           0x01, 0x01, 0x01, 0x01, 0x02, 0x04};

/* ---- 全局变量 ---- */
uchar disp[8];              /* 8 位数码管显示缓存，存段码表索引 */
uchar ring_buf[4];          /* 左块 4 位的环形进度段码（拆包时用） */
uchar state = ST_IDLE;

uint  charge_ms   = 0;      /* 充能累计 ms */
uint  charge_tick = 0;      /* 充能亮灯节拍（要到 500，必须 uint） */
uint  remain_10ms = 0;      /* 剩余时间，单位 10ms（45 秒 = 4500） */
uchar cur_sec     = PLANT_SEC;
uchar cur_frac    = 0;      /* 百分秒 0~99 */
uchar light_cnt   = 0;      /* 已亮 LED 个数 */
uint  tick_acc    = 0;      /* 滴答间隔累计 */
uint  hold_ms     = 0;      /* 拆包长按累计 */
uchar ms10_acc    = 0;      /* 10ms 累加 */

uchar beep_left = 0;        /* 蜂鸣器剩余响时间 ms */
uchar beep_gap  = 0;        /* 两声之间的间隔计数 */
uchar beep_seq  = 0;        /* 是否还排着第二声 */

uchar scan    = 0;          /* 数码管扫描位 */
uchar led_val = LED_OFF;    /* 当前 LED 图案（低电平有效） */
uchar pwm_cnt = 0;          /* LED PWM 计数 0~4 */
uint  blink_cnt = 0;        /* 最后 10 秒急闪计时 */
uchar tick1ms = 0;          /* 待处理的 1ms 节拍数（主循环消费） */

bit blink_on     = 1;
bit ring_on      = 0;       /* 左块是否显示环形进度 */
bit defusing     = 0;       /* 拆包键当前是否按住 */
bit flag_plant   = 0;       /* 充能完成 */
bit flag_defused = 0;       /* 拆包成功 */
bit flag_explode = 0;       /* 时间到爆炸 */
bit flag_split   = 0;       /* 充能中断 */

/* ---- 外部中断捕获的按键状态（1 = 已按下） ---- */
bit k_plant_hold  = 0;      /* INT1 捕获到 S2 按下 */
bit k_defuse_hold = 0;      /* INT0 捕获到 S3 按下 */

/* ================= 外部中断 ================= */
/* INT0：拆包键 S3 下降沿触发，只置标志，不做重活，绝不占用时基 */
void isr_int0(void) interrupt 0
{
    k_defuse_hold = 1;
}

/* INT1：下包键 S2 下降沿触发 */
void isr_int1(void) interrupt 2
{
    k_plant_hold = 1;
}

/* ================= 基础函数 ================= */
/* 数码管全部熄灭（写 11 = 空段码） */
void disp_off(void)
{
    uchar i;
    for (i = 0; i < 8; i++) disp[i] = 11;
    ring_on = 0;
}

/* 显示 ss.ff（右 4 位，小数点在 disp[5]） */
void show_time(uchar s, uchar f)
{
    uchar i;
    for (i = 0; i < 8; i++) disp[i] = 11;
    disp[4] = (uchar)(s / 10);
    disp[5] = (uchar)(s % 10);
    disp[6] = (uchar)(f / 10);
    disp[7] = (uchar)(f % 10);
}

/* 拆包环形进度：左块 4 位外框点亮 cnt 段（0~12），顺时针走一圈 */
void show_ring(uchar cnt)
{
    uchar i;
    for (i = 0; i < 4; i++) ring_buf[i] = 0;
    if (cnt > 12) cnt = 12;
    for (i = 0; i < cnt; i++) ring_buf[ring_pos[i]] |= ring_seg[i];
    ring_on = 1;
}

/* 8 位全部亮起（全部显示 8） */
void show_all(void)
{
    uchar i;
    for (i = 0; i < 8; i++) disp[i] = 8;
    ring_on = 0;
}

/* 居中显示 4 个字母（占 disp[2]~disp[5]） */
void show_word(uchar a, uchar b, uchar c, uchar d)
{
    uchar i;
    for (i = 0; i < 8; i++) disp[i] = 11;
    disp[2] = a;
    disp[3] = b;
    disp[4] = c;
    disp[5] = d;
    ring_on = 0;
}

/* ================= 数码管扫描（主循环里，每次点一位） ================= */
/* 先位选、后段选；每位停留 1ms，8 位一帧 8ms（125Hz） */
void scan_one(void)
{
    uchar d;

    P0 = pos[scan];
    WE = 1; WE = 0;

    d = seg[disp[scan]];
    if (scan < 4 && ring_on) d = ring_buf[scan];          /* 左块：拆包环形进度 */
    if (scan == DOT_POS && disp[scan] <= 9) d |= 0x80;    /* 数字位叠小数点 */

    P0 = d;
    DU = 1; DU = 0;

    scan++;
    if (scan > 7) scan = 0;
}

/* ================= 1ms 逻辑（主循环里按 tick1ms 调用） ================= */
void tick_logic(void)
{
    uchar ext;
    uint gap, tmp;

    /* ---- LED PWM 调亮度：5ms 一周期（200Hz），占空比 LED_DUTY/5 ---- */
    pwm_cnt++;
    if (pwm_cnt >= 5) pwm_cnt = 0;
    if (pwm_cnt < LED_DUTY) P1 = led_val;
    else                    P1 = LED_OFF;

    /* ---- 充能状态 ---- */
    if (state == ST_CHARGING) {
        if (k_plant_hold) {
            if (charge_ms < CHARGE_MS) charge_ms++;

            if (charge_ms == 200) {                 /* 按下 0.2 秒后：嘀嘀两声 */
                beep_left = 60;
                beep_seq  = 1;
                beep_gap  = 100;
            }

            charge_tick++;
            if (charge_tick >= CHARGE_STEP) {       /* 每 500ms 亮一个灯 */
                charge_tick = 0;
                if (light_cnt < 8) light_cnt++;     /* 只亮，不出声 */
            }

            led_val = on_tab[light_cnt];

            if (charge_ms >= CHARGE_MS) flag_plant = 1;
        } else {
            charge_ms   = 0;                        /* 中途松开：充能清零 */
            charge_tick = 0;
            light_cnt   = 0;
            beep_seq    = 0;
            beep_gap    = 0;
            led_val     = LED_OFF;
            flag_split  = 1;
        }

        /* 蜂鸣器：单声 + 两声序列 */
        if (beep_left) {
            BEEP = 0;
            beep_left--;
        } else {
            BEEP = 1;
            if (beep_seq) {
                if (beep_gap) beep_gap--;
                if (beep_gap == 0) {
                    beep_left = 60;
                    beep_seq  = 0;
                    beep_gap  = 100;
                }
            }
        }
        return;
    }

    if (state != ST_PLANTED) return;

    /* ---- 蜂鸣器控制 ---- */
    if (beep_left) { BEEP = 0; beep_left--; }
    else BEEP = 1;

    /* ---- 10ms 精细倒计时（小数点后两位） ---- */
    ms10_acc++;
    if (ms10_acc >= 10) {
        ms10_acc = 0;
        if (remain_10ms) remain_10ms--;
        tmp = remain_10ms;
        cur_sec  = (uchar)(tmp / 100);
        cur_frac = (uchar)(tmp % 100);
        if (remain_10ms == 0) { flag_explode = 1; return; }
    }

    /* ---- 最后 10 秒数码管急闪（200ms 亮 / 200ms 灭） ---- */
    if (remain_10ms <= 1000) {
        blink_cnt++;
        if (blink_cnt >= 200) { blink_cnt = 0; blink_on = !blink_on; }
    } else {
        blink_cnt = 0;
        blink_on = 1;
    }

    /* ---- 滴答节奏：四档阶跃 + 最后 0.5 秒长鸣 ---- */
    if (remain_10ms <= 50) {
        beep_left = 60;                             /* 最后 0.5 秒：长鸣不停 */
        tick_acc  = 0;
    } else {
        gap = (remain_10ms <= 500)  ? 125 :         /* 剩余 5~0.5 秒 */
              (remain_10ms <= 1000) ? 250 :         /* 剩余 10~5 秒 */
              (remain_10ms <= 2250) ? 500 :         /* 剩余 22.5~10 秒 */
                                      1000;         /* 剩余 45~22.5 秒 */
        tick_acc++;
        if (tick_acc >= gap) {
            tick_acc = 0;
            beep_left = 25;
        }
    }

    /* ---- 长按拆包计时（Valorant 半拆机制：3.5 秒为存档点） ---- */
    if (k_defuse_hold) {
        defusing = 1;
        if (hold_ms < HOLD_MS) hold_ms++;
        if (hold_ms == HOLD_MS / 2) beep_left = 40; /* 到达半拆点：嘀一声 */
        if (hold_ms >= HOLD_MS) flag_defused = 1;
    } else {
        if (defusing) {
            defusing = 0;
            if (hold_ms < HOLD_MS / 2) {
                hold_ms = 0;                        /* 未到半拆：进度清零 */
            } else {
                hold_ms = HOLD_MS / 2;              /* 已过半拆：退到存档点 */
            }
        }
    }

    /* ---- LED 输出（优先级：拆包进度 > 半拆存档 > 滴答脉冲） ---- */
    if (defusing || hold_ms >= HOLD_MS / 2) {
        ext = (uchar)(hold_ms / 875);               /* 每 875ms 熄灭一个灯 */
        if (ext > 8) ext = 8;
        led_val = defuse_tab[ext];
    } else if (beep_left) {
        led_val = LED_ON;                           /* 响的同时 8 灯全亮 */
    } else {
        led_val = LED_OFF;                          /* 响完熄灭 */
    }

    /* ---- 数码管内容（每 10ms 刷新一次）
     * 左块 disp[0..3]：拆包环形进度；右块 disp[4..7]：倒计时，始终照常显示 ---- */
    if (ms10_acc == 0) {
        if (defusing || hold_ms >= HOLD_MS / 2) {
            show_time(cur_sec, cur_frac);           /* 右块：倒计时不动 */
            show_ring((uchar)(hold_ms / 583));      /* 左块：12 段一圈，583ms 一段 */
        } else if (remain_10ms <= 1000 && blink_on == 0) {
            disp_off();                             /* 急闪的灭相 */
        } else {
            ring_on = 0;
            show_time(cur_sec, cur_frac);
        }
    }
}

/* ================= T0 中断：只维护 1ms 时基 ================= */
/* 重装初值 + 判松手 + 节拍加一，全部指令加起来不到 40 个机器周期，
 * 远小于 1ms 的 922 个机器周期，因此绝不会漏计溢出              */
void isr_t0(void) interrupt 1
{
    TH0 = 0xFC;
    TL0 = 0x66;

    /* 松手检测：下降沿只报一次按下，松手靠 1ms 时基判定 */
    if (k_plant_hold  && K_PLANT  == 1) k_plant_hold  = 0;
    if (k_defuse_hold && K_DEFUSE == 1) k_defuse_hold = 0;

    if (tick1ms < TICK_MAX) tick1ms++;      /* 交给主循环消费 */
}

/* ================= 等待 N 个 1ms 节拍（期间显示与逻辑照常运行） ================= */
void wait_ms(uint ms)
{
    while (ms) {
        if (tick1ms) {
            tick1ms--;
            tick_logic();
            scan_one();
            ms--;
        }
    }
}

/* ================= 流程控制 ================= */
/* 下包成功：开始倒计时 */
void start_plant(void)
{
    state = ST_PLANTED;
    remain_10ms = (uint)PLANT_SEC * 100;    /* 4500 = 45.00 秒 */
    cur_sec  = PLANT_SEC;
    cur_frac = 0;
    light_cnt = 8;
    tick_acc  = 0;
    hold_ms   = 0;
    ms10_acc  = 0;
    blink_cnt = 0;
    blink_on  = 1;
    defusing  = 0;
    flag_explode = 0;
    flag_defused = 0;
    beep_seq  = 0;
    beep_gap  = 0;
    beep_left = 40;                         /* 下包完成提示音 */
    led_val   = LED_ON;                     /* 全亮 */
    ring_on   = 0;
    show_time(PLANT_SEC, 0);                /* 显示 45.00 */
}

/* 拆包成功：SFHS 守方获胜 */
void do_defused(void)
{
    state = ST_DEFUSED;
    BEEP = 1;
    blink_on = 1;
    led_val  = LED_OFF;

    /* 8 位数码管全部亮起 */
    show_all();
    wait_ms(600);

    /* 显示 SFHS（守方获胜），8 个 LED 一起亮着 */
    show_word(12, 13, 14, 12);              /* S F H S */
    led_val = LED_ON;
    wait_ms(2500);

    led_val = LED_OFF;
    disp_off();
    state = ST_IDLE;
}

/* 爆炸：GFHS 攻方获胜 */
void do_explode(void)
{
    uchar t;
    state = ST_EXPLODED;

    /* 爆炸：全亮急闪 + 蜂鸣 2 秒 */
    for (t = 0; t < 10; t++) {
        led_val = LED_ON;  BEEP = 0; wait_ms(100);
        led_val = LED_OFF; BEEP = 1; wait_ms(100);
    }
    BEEP = 0; wait_ms(800); BEEP = 1;
    led_val = LED_OFF;

    /* 8 位数码管全部亮起 */
    show_all();
    wait_ms(600);

    /* 显示 GFHS（攻方获胜） */
    show_word(15, 13, 14, 12);              /* G F H S */
    wait_ms(2500);

    disp_off();
    state = ST_IDLE;
}

/* ================= 主函数 ================= */
void main(void)
{
    disp_off();                             /* 待机：数码管全灭 */
    BEEP    = 1;
    led_val = LED_OFF;
    P1      = LED_OFF;                      /* LED 全灭 */
    P0      = 0x00;

    TMOD = 0x01;
    TH0  = 0xFC;
    TL0  = 0x66;
    ET0  = 1;
    TR0  = 1;

    /* 外部中断：INT0(拆包 S3) / INT1(下包 S2) 均为下降沿触发，EA 最后开 */
    IT0  = 1;
    IT1  = 1;
    EX0  = 1;
    EX1  = 1;
    EA   = 1;

    while (1) {
        /* ---- 每个 1ms 节拍：跑一次逻辑 + 推进一位显示 ---- */
        if (tick1ms) {
            tick1ms--;
            tick_logic();
            scan_one();
        }

        /* ---- 状态机（全部非阻塞） ---- */
        if (state == ST_IDLE) {
            led_val = LED_OFF;              /* 待机确保全灭 */
            if (k_plant_hold) {             /* 外部中断捕获到下包键按下 */
                wait_ms(20);
                if (k_plant_hold) {
                    charge_ms   = 0;
                    charge_tick = 0;
                    light_cnt   = 0;
                    beep_left   = 0;
                    beep_gap    = 0;
                    beep_seq    = 0;
                    disp_off();
                    state = ST_CHARGING;    /* 进入充能，等长按满 4 秒 */
                }
            }
        }
        else if (state == ST_CHARGING) {
            if (flag_plant) {               /* 充能完成 */
                flag_plant = 0;
                start_plant();
            }
            else if (flag_split) {          /* 中途松开 */
                flag_split = 0;
                state = ST_IDLE;
                led_val = LED_OFF;
                BEEP = 1;
                disp_off();
            }
        }
        else if (state == ST_PLANTED) {
            if (flag_defused)      { flag_defused = 0; do_defused(); }
            else if (flag_explode) { flag_explode = 0; do_explode(); }
        }
    }
}
