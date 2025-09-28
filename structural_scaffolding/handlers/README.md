# `python_handler.py` 工作原理详解

## 1. 概述 (Overview)

`python_handler.py` 文件是一个专门为 Python 语言设计的**静态代码分析器**。

它的核心任务是读取一个 `.py` 源代码文件，解析其内部的语法结构，并提取出代码中所有重要单元（如文件本身、类、函数/方法）的详细元信息。最终，它会将这些信息封装成一系列结构化的 `Profile` 对象。

简而言之，它不**执行**代码，而是像阅读建筑蓝图一样**理解**代码的结构。

## 2. 核心组件 (Core Components)

整个文件围绕以下几个关键类进行组织：

-   **`PythonHandler`**: 这是暴露给外部的**主接口**。它负责接收文件路径，读取文件内容，并启动整个解析流程。它继承自 `BaseLanguageHandler`，表明这是一个可扩展的、针对特定语言的处理器。

-   **`PythonProfileBuilder`**: 这是真正的**核心解析引擎**。它负责执行最关键的任务：
    1.  接收 `tree-sitter` 解析器和源代码。
    2.  将源代码文本解析成一个抽象语法树 (AST)。
    3.  遍历这棵 AST。
    4.  构建描述代码结构的 `Profile` 对象。

-   **`PythonNodeContext`**: 这是一个轻量级的数据类 (`dataclass`)，用于在解析流程中方便地传递上下文信息，主要包含 `source_bytes` (源文件字节) 和 `relative_path` (文件相对路径)。

-   **`Profile` (来自 `models.py`)**: 这是最终输出的**数据模型**。每一个 `Profile` 实例都代表了代码中的一个结构化单元（一个文件、一个类或一个函数），并包含了关于该单元的丰富元信息（如名称、行号、源代码、文档字符串、参数、内部调用等）。

## 3. 工作流程 (Workflow)

`python_handler.py` 的工作流程是一个清晰的、自上而下的管道：

1.  **读取文件**: 流程始于 `PythonHandler.extract` 方法。它首先以**二进制模式** (`.read_bytes()`) 读取目标 `.py` 文件。使用字节而不是文本可以避免编码问题，并且是 `tree-sitter` 的要求。

2.  **创建上下文**: 文件内容和路径被封装进一个 `PythonNodeContext` 实例中。

3.  **解析为 AST**: `PythonProfileBuilder` 被实例化，并调用 `tree-sitter` 解析器将文件的字节流转换成一个**抽象语法树 (AST)**。AST 是代码语法的内存中树状表示，是静态分析的基础。

4.  **遍历 AST**: 从 AST 的根节点 (`root_node`) 开始，`PythonProfileBuilder` 采用**深度优先遍历 (Depth-First Traversal)** 的策略，系统地访问树中的节点。

5.  **构建 Profiles**: 在遍历过程中，`_collect_child_profiles` 方法负责识别当前节点的直接子节点中是否有我们关心的类型（`function_definition` 和 `class_definition`）。
    -   如果找到一个函数或类，它会调用相应的 `_build_function_profile` 或 `_build_class_profile` 方法。
    -   这些 `_build_*` 方法负责从该节点中提取所有相关的元信息，并创建一个对应的 `Profile` 对象。

6.  **返回结果**: 遍历完成后，`extract` 方法会返回一个扁平化的 `Profile` 对象列表。这个列表完整地、结构化地描述了整个 Python 文件的代码布局。

## 4. 算法效率 (Algorithm Efficiency)

这是一个非常关键的问题：这个文件高效吗？会不会重复遍历代码？

-   **高效性**: 该文件的算法**非常高效**。其时间复杂度为 **O(N)**，其中 N 是源代码解析后 AST 中的节点总数。对于需要完整扫描一次文件的静态分析任务来说，这是理论上能达到的最优时间复杂度。

-   **单次遍历保证**: 算法的设计**从根本上保证了不会重复遍历同一个代码区域**。

-   **工作原理类比 (The Family Tree Analogy)**:
    为了更好地理解这一点，我们可以将 AST 想象成一个**家族族谱**：
    -   文件节点是最高层的**曾祖父**。
    -   文件内定义的类是**儿子**。
    -   类内定义的方法是**孙子**。

    `PythonProfileBuilder` 的工作方式就像一个严谨的**人口普查员**：
    1.  普查员从**曾祖父**（文件根节点）开始，只问他一个问题：“你的**直接孩子**是谁？”
    2.  当他找到一个**儿子**（类节点）后，他会转向这个儿子，再问同样的问题：“你的**直接孩子**是谁？”。他**绝对不会**再回头去问曾祖父任何问题。
    3.  这个过程是一个严格的、从上到下的**责任委托链**。`_build_file_profile` 只负责文件级别，然后将分析其子节点的任务委托给 `_collect_child_profiles`。`_collect_child_profiles` 找到子节点后，又将分析子节点内部的任务委托给相应的 `_build_class_profile` 或 `_build_function_profile`。

    这种经典的**深度优先遍历**策略确保了 AST 中的每个节点在整个分析过程中都**只被访问和处理一次**，从而避免了任何冗余工作，保证了整个流程的高效性。

## 5. 辅助函数 (Helper Functions)

在文件的底部，定义了许多独立的辅助函数，如 `extract_parameters`、`collect_calls`、`extract_docstring` 等。

这些函数遵循了“单一职责原则”，将复杂的解析任务（例如从函数节点中提取所有参数、从代码块中收集所有函数调用）分解为独立的、可测试、可重用的单元。这使得 `PythonProfileBuilder` 的主逻辑更加清晰和易于维护。
