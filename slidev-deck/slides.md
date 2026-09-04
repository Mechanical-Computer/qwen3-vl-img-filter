---
theme: default
title: 雨雾天气图片数据挖掘
info: 基于 Qwen3-VL 与 vLLM 的自动驾驶数据闭环实践
highlighter: shiki
lineNumbers: false
transition: fade-out
aspectRatio: '16/9'
fonts:
  sans: 'Noto Sans SC'
  mono: 'JetBrains Mono'
  weights: '300,400,500,700,900'
  provider: 'google'
drawings:
  persist: false
layout: cover
class: cover-slide
---

<div class="cover-inner">

<div class="kicker">实习项目 · 自动驾驶数据闭环 · 2025.12</div>

# 雨雾天气图片数据挖掘

<div class="cover-sub">基于 Qwen3-VL 与 vLLM 的大规模图像筛选实践</div>

<div class="telemetry">
  <span class="t-item"><span class="dot live"></span>CAM_FRONT_MIDDLE</span>
  <span class="t-item">8 相机视角</span>
  <span class="t-item">16 并发</span>
  <span class="t-item">Qwen3-VL-32B · FP8</span>
  <span class="t-item">L20 · 48G</span>
</div>

</div>

<!-- ============ 2 背景 ============ -->

---
layout: two-cols
class: slide-pad
---

# 背景 · 比赛卡在雨雾

<div class="card pain">
  <div class="card-title">⚙️ 事故复盘</div>
  <ul>
    <li>公司参加 2025.12 物流车比赛，<span class="hl">雨雾环节卡住</span></li>
    <li>事后分析：激光雷达感知到「<span class="hl">虚影</span>」</li>
    <li>虚影被误判为障碍物 → 车辆停下</li>
  </ul>
</div>

<div class="card task">
  <div class="card-title">🎯 我的任务</div>
  <ul>
    <li>找出数据集中<span class="hl">雨雾天气的图片</span></li>
    <li>借此定位对应的<span class="hl">激光雷达点云数据</span></li>
    <li>交给团队做<span class="hl">加强训练</span></li>
  </ul>
</div>

::right::

<div class="ghost-title">数据闭环</div>

<div class="flow">
  <div class="flow-step"><span class="flow-num">01</span>挖掘雨雾图片</div>
  <div class="flow-arrow">↓</div>
  <div class="flow-step"><span class="flow-num">02</span>定位点云数据</div>
  <div class="flow-arrow">↓</div>
  <div class="flow-step"><span class="flow-num">03</span>加强训练</div>
  <div class="flow-arrow">↓</div>
  <div class="flow-step"><span class="flow-num">04</span>模型迭代</div>
</div>

<div class="note">一句话：大模型挖掘数据 → 反哺感知模型 → 形成数据飞轮</div>

<!-- ============ 3 方案选型 ============ -->

---
class: slide-pad
---

# 方案选型 · 从小模型验证到规模应用

<div class="grid grid-cols-3 gap-5 mt-10">

<div class="card step-card">
  <div class="step-num">01</div>
  <div class="card-title">mentor 建议</div>
  <p>使用多个视觉语言大模型做<b>交叉验证</b>，提升挖掘可信度</p>
</div>

<div class="card step-card">
  <div class="step-num">02</div>
  <div class="card-title">本地先试小模型</div>
  <p>在 <b>ModelScope</b> 调研模型规模，先用 <b>Qwen3-VL-4B</b> 本地测试几张图片</p>
</div>

<div class="card step-card">
  <div class="step-num">03</div>
  <div class="card-title">放大到生产</div>
  <p>4B 描述基本准确可信 → 在 <b>48G 显存的 L20</b> 上部署 <b>32B</b> 调试应用</p>
</div>

</div>

<div class="note mt-8">验证路径：4B 可行性验证 → 32B 规模应用 —— 小模型验证思路，大模型落地效果</div>

<!-- ============ 4 系统架构 ============ -->

---
class: slide-pad
---

# 系统架构 · 一条流水线

<div class="arch-img">
  <img src="/structure.png" alt="整体处理流程架构图" />
</div>

<div class="chips">
  <span class="chip">① 扫描样本目录</span>
  <span class="chip">② 图像预处理（缩放）</span>
  <span class="chip">③ 16 并发推理</span>
  <span class="chip">④ 相机级投票</span>
  <span class="chip">⑤ 场景判定落盘</span>
</div>

<!-- ============ 5 协程核心 ============ -->

---
class: slide-pad
---

# 并发核心 · asyncio 三件套

<div class="grid grid-cols-3 gap-5 mt-10">

<div class="card">
  <div class="card-title mono">coroutine · 协程</div>
  <p>可「挂起 / 恢复」的函数：遇到 I/O 阻塞就让出控制权，不占线程</p>
</div>

<div class="card">
  <div class="card-title mono">task · 任务</div>
  <p>协程包装成 Task 交给事件循环调度，多个任务在单线程里交替前进</p>
</div>

<div class="card">
  <div class="card-title mono">event loop · 事件循环</div>
  <p>单线程调度器：谁就绪谁运行，统一管理 I/O 回调与定时器</p>
</div>

</div>

<div class="grid grid-cols-3 gap-5 mt-5">

<div class="card dim">
  <span class="hl">16 个 worker</span> 协程并行消费任务
</div>

<div class="card dim">
  <span class="hl">asyncio.Queue</span> 有界队列做背压
</div>

<div class="card dim">
  <span class="hl">aiohttp</span> 连接池复用 HTTP 连接
</div>

</div>

<div class="note mt-8">并发提速的前提：服务端 vLLM 连续批处理，把并发请求拼进同一计算步</div>

<!-- ============ 6 接口验证 ============ -->

---
layout: two-cols
class: slide-pad
---

# 接口验证 · 单图测试

<div class="code-xs">

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "./Qwen3-VL-4B-Instruct",
    "messages": [{
      "role": "user",
      "content": [
        {"type": "text", "text": "这张图里有雨或雾吗？只回答有/无"},
        {"type": "image_url",
         "image_url": {"url": "file:///media/.../CAM_FRONT_MIDDLE/xxx.jpg"}}
      ]
    }],
    "max_tokens": 10,
    "temperature": 0.0
  }'
```

</div>

::right::

<div class="card mt-10">
  <div class="card-title">要点</div>
  <ul>
    <li><span class="hl">OpenAI 兼容接口</span>：<code>/v1/chat/completions</code></li>
    <li><span class="hl">多模态输入</span>：text + image_url 混合 content</li>
    <li><span class="hl">temperature 0</span>：贪心解码，输出确定</li>
    <li>先用 4B 模型验证思路可行</li>
  </ul>
</div>

<!-- ============ 7 部署命令 ============ -->

---
layout: two-cols
class: slide-pad
---

# 模型部署 · vLLM

<div class="card dark-card">
  <div class="card-title mono">旧版启动命令</div>
  <div class="code-xs">

```python
python -m vllm.entrypoints.openai.api_server \
    --model ./Qwen3-VL-32B-Instruct-FP8 \
    --max-model-len 4096 \
    --gpu-memory-utilization 0.75 \
    --port 8000 \
    --allowed-local-media-path /media/
```

  </div>
</div>

::right::

<div class="card dark-card">
  <div class="card-title mono">新版启动命令</div>
  <div class="code-xs">

```python
vllm serve ./Qwen3-VL-32B-Instruct-FP8
```

  </div>
  <div class="note">新版 CLI 更简洁，底层升级为 V1 引擎（前缀缓存默认开启）</div>
</div>

<!-- ============ 8 关键参数 ============ -->

---
class: slide-pad
---

# 关键参数 · 为什么这么设

<div class="grid grid-cols-3 gap-5 mt-10">

<div class="card">
  <div class="card-title mono">--max-model-len 4096</div>
  <p>单请求上下文上限：<b>给每个请求的 KV Cache 封顶</b>，防止超长请求吃光显存</p>
  <div class="note">图像 token 也计入其中</div>
</div>

<div class="card">
  <div class="card-title mono">--gpu-memory-utilization 0.75</div>
  <p>显存总预算：48G × 0.75 = 36G，权重 32G+ 之外留给 KV 池与激活值</p>
  <div class="note">32B 单卡部署 = 贴线作战</div>
</div>

<div class="card">
  <div class="card-title mono">--allowed-local-media-path /media/</div>
  <p>file:// 图片读取<b>白名单</b>，只允许该目录前缀，防止任意文件读取</p>
  <div class="note">服务端安全边界</div>
</div>

</div>

<div class="note mt-8">配套：PIL 缩放到 1024 控制图像 token —— 每一处都是显存约束下的权衡</div>

<!-- ============ 9 参考与总结 ============ -->

---
layout: center
class: slide-pad
---

# 参考链接

<div class="grid grid-cols-2 gap-5 mt-10">

<a class="card link-card" href="https://recipes.vllm.ai/Qwen/Qwen3-VL-30B-A3B-Instruct" target="_blank">
  <div class="card-title">vLLM 部署模型</div>
  <div class="mono dim">recipes.vllm.ai</div>
</a>

<a class="card link-card" href="https://github.com/QwenLM/Qwen3-VL#3" target="_blank">
  <div class="card-title">Qwen3-VL · GitHub</div>
  <div class="mono dim">github.com/QwenLM/Qwen3-VL</div>
</a>

</div>

<div class="endline">THANKS · 欢迎讨论</div>
