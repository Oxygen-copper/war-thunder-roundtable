# 战雷涂装库 · 说明（已更正）

## 一、结论更正：能放多套，但必须"一个文件夹 = 一套"

上一版写的是"一个载具文件夹只能有一套涂装"——**前半句对，结论下错了**。

准确的机制是：

- **一个文件夹 = 一套涂装**：往同一个文件夹里再塞第二套，游戏不会认；
- 但**同一台车可以同时装很多套** —— 每套各占 `UserSkins\` 下的**一个独立文件夹**，并列摆着就行。

依据：

1. Gaijin 官方论坛《Is it possible to shuffle userskins?》里的回答：
   > You can have more than one skin per vehicle, you just need to rename the file ...
   > only the folder file.
   （一台车可以有多套皮肤，只要把**文件夹**改成不重名的名字。）
2. 游戏自己的文本 `lang\menu_options.csv`：
   - `decals/userSkinSample` = **创建涂装范本**
   - `decals/updateSkinsList/tooltip` = **更新自定涂装列表（并重新载入当前涂装）**
   - 列表项的显示名来自 `userSkin/custom`，值是 `%s` → 直接拿**文件夹名**来显示。

## 二、上次为什么"没变"？两个坑叠在一起

1. **塞错了层级**：第二套被塞进 `template_uk_a_22b_mk_3_churchill_1942\` **里面**。
   游戏在这个文件夹里只认**那一个** `uk_a_22b_mk_3_churchill_1942.blk`，多出来的文件一律无视。
2. **那套测试皮本身是坏的**：它的 `.blk` 里写的是
   `to:t="test_camo_2.tga"` / `test_body_2.tga` / `test_turret_2.tga` / `test_gun_2.tga`，
   而文件夹里实际的文件叫 `uk_a_22b_mk_3_churchill_1942_body.tga` 之类 —— **名字对不上**。
   就算放对位置，也只会变成一堆贴图丢失。

两个坑叠在一起，结果当然是"没变"。现在两处都已修好。

## 三、正确的目录长什么样

```
<游戏根目录>\UserSkins\
    template_uk_a_22b_mk_3_churchill_1942\   ← 游戏自己生成的，它本身也是"一套"
    Churchill Mk.III - 品红测试\             ← 你的第 2 套
        uk_a_22b_mk_3_churchill_1942.blk     ← 文件名必须 = 载具ID
        a22b_mk_iii_churchill_1942_body.tga
        a22b_mk_iii_churchill_1942_turret.tga
        a22b_mk_iii_churchill_1942_gun.tga
        uk_camo_very_dark_drab.tga
    Churchill Mk.III - 以后随便加\
        ...
```

三条硬规则：

1. 每个套装文件夹里**至少有一个 `.blk`，且文件名 = 载具ID**
   （丘吉尔 Mk.III 就是 `uk_a_22b_mk_3_churchill_1942.blk`）；
2. **套装文件夹的名字随便起**（它就是游戏里显示的名字），只要彼此不重名；
3. 文件夹里**别放 `.blk` 没引用的杂物** —— 报市场会被退稿。

顺带：`.blk` 里 `to:t="..."` 的贴图名也必须和实际文件**逐字一致**（大小写也要一致）。

## 四、在游戏里怎么调出来

1. `车辆 → 外观定制 → 迷彩`；
2. 找到 **「自定涂装」** 那一组 —— 里面每一项就是你的**文件夹名**；
3. 改完内容点 **「更新自定涂装列表」**（它会顺便重新载入当前涂装）；
4. 如果「自定涂装」整组都不出现，去 `选项` 里看那个叫 **「自定涂装」** 的开关是不是被关了。

## 五、涂装工坊（网页版）

```
D:\AI\战雷涂装\
    启动工坊.bat          ← 双击这个，浏览器会自己打开
    server.py             ← 本地后端（纯 Python 标准库，不用装任何包）
    web\                  ← 网页
    工具\                  ← 引擎，平时不用碰
        texconv.exe / 转换DDS-拖文件夹.bat / check_skin_compat.py / GIMP-启动.bat
    色板\
        Churchill-藏蓝棕米.gpl
    涂装库\
        uk_a_22b_mk_3_churchill_1942\    ← 载具ID
            Churchill Mk.III - 原厂范例\  ← 一套 = 一个文件夹（母版）
            Churchill Mk.III - 品红测试\
            Churchill Mk.III - 藏蓝棕米\
```

双击 `启动工坊.bat` → 浏览器打开 `http://127.0.0.1:8788`。页面上能做的事：

- 左侧选载具，右侧是涂装卡片（自动出缩略图、"已装进游戏"状态）
- 一键：装进游戏 / 用 GIMP 打开 / 转 DDS / 看 `.blk` / 打开文件夹 / 改名 / 删除
- 新建涂装（从现有母版复制）
- 把整套涂装文件夹或 `.zip` **直接拖到网页上**就能导入
- 跨载具通用性检查，结果直接显示在页面上
- 右上角「设置」里改游戏路径和 GIMP 路径（换电脑或给别人用时用得上）

关掉那个黑色窗口 = 关掉工坊。以前那套命令行菜单和"先清空再拷入"的切换模式都已作废 —— 现在几套涂装并列共存，不需要清空。
