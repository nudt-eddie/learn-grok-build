export const meta = {
  name: 'learn-grok-build-full',
  description: '全面分析 Grok Build 源码并撰写文档库',
  phases: ['分析核心模块', '撰写架构文档', '撰写核心系统文档', '撰写扩展系统文档'],
}

const CORE_MODULES = [
  { path: 'source/crates/codegen', key: '架构总览' },
  { path: 'source/crates/codegen/xai-grok-agent', key: 'Agent核心' },
  { path: 'source/crates/codegen/xai-grok-tools', key: '工具系统' },
  { path: 'source/crates/codegen/xai-grok-workspace', key: '工作区' },
  { path: 'source/crates/codegen/xai-chat-state', key: '状态管理' },
]

phase('分析核心模块')
const analyses = await parallel(CORE_MODULES.map(m => () =>
  agent('你是Grok Build源码分析专家。深入分析' + m.path + '目录下的代码：模块职责与设计模式、核心数据结构、关键API接口、模块间依赖关系、重要流程。用JSON输出完整分析报告，包含summary、responsibilities、key_structs、key_apis、dependencies、key_flows、important_notes字段。', {label: 'analyze:' + m.key}).catch(e => ({ module: m.key, error: e.message }))
))

const validAnalyses = analyses.filter(Boolean)
log('分析了' + validAnalyses.length + '个核心模块')

phase('撰写架构文档')
const archDoc = await agent('基于以下模块分析结果，撰写Grok Build总体架构文档。分析结果：' + JSON.stringify(validAnalyses) + '请撰写完整Markdown文档到D:/Desktop/code/learn-grok-build/docs/01-architecture/README.md，包含：项目概述、技术栈、Crate架构地图、三种运行模式、核心组件描述、设计模式总结。返回{saved_path:"文件路径"}', {schema: {type:'object',properties:{saved_path:{type:'string'}}}})

phase('撰写核心系统文档')

const docTasks = [
  { key: 'Agent核心', output: 'D:/Desktop/code/learn-grok-build/docs/04-agent-loop/README.md', title: 'Agent Loop' },
  { key: '工具系统', output: 'D:/Desktop/code/learn-grok-build/docs/06-tool-system/README.md', title: '工具系统' },
  { key: '工作区', output: 'D:/Desktop/code/learn-grok-build/docs/07-workspace/README.md', title: '工作区系统' },
  { key: '状态管理', output: 'D:/Desktop/code/learn-grok-build/docs/08-session-memory/README.md', title: '会话与状态管理' },
]

const coreDocs = await parallel(docTasks.map(t => () =>
  agent('基于分析结果撰写' + t.title + '文档。分析结果：' + JSON.stringify(validAnalyses.find(a => a.module === t.key)) + '输出完整Markdown到' + t.output + '，包含概述、核心数据结构、关键流程、API接口、设计模式等详细内容。返回{saved_path:"路径"}', {schema: {type:'object',properties:{saved_path:{type:'string'}}}})
))

phase('分析扩展系统')
const extModules = [
  { path: 'source/crates/codegen/xai-grok-mcp', key: 'MCP' },
  { path: 'source/crates/codegen/xai-grok-hooks', key: 'Hooks' },
  { path: 'source/crates/codegen/xai-grok-sandbox', key: 'Sandbox' },
  { path: 'source/crates/codegen/xai-grok-memory', key: 'Memory' },
]

const extAnalyses = await parallel(extModules.map(m => () =>
  agent('分析' + m.path + '模块，输出JSON分析报告包含summary、key_structs、key_apis、design_notes。', {label: 'ext:' + m.key}).catch(e => ({module: m.key, summary: e.message}))
))

phase('撰写扩展系统文档')
await agent('基于扩展模块分析撰写Extensions系统文档。分析：' + JSON.stringify(extAnalyses.filter(Boolean)) + '输出完整Markdown到D:/Desktop/code/learn-grok-build/docs/10-extensions/README.md，包含MCP、Hooks、Sandbox、Memory、TUI、Headless、ACP等扩展机制。返回{saved_path:"路径"}', {schema: {type:'object',properties:{saved_path:{type:'string'}}}})

phase('撰写其他文档')
await parallel([
  () => agent('分析source入口文件和启动流程，输出Markdown到D:/Desktop/code/learn-grok-build/docs/02-startup/README.md，包含入口点、配置加载、组件初始化、服务启动流程。返回{saved_path}', {schema: {type:'object',properties:{saved_path:{type:'string'}}}}),
  () => agent('分析上下文组装代码，输出Markdown到D:/Desktop/code/learn-grok-build/docs/05-context-assembly/README.md，包含系统提示词构建、用户上下文、工具描述、历史消息、Token预算管理。返回{saved_path}', {schema: {type:'object',properties:{saved_path:{type:'string'}}}}),
  () => agent('分析权限和沙箱机制，输出Markdown到D:/Desktop/code/learn-grok-build/docs/09-permissions/README.md，包含权限模型、隔离机制、文件访问控制、信任等级。返回{saved_path}', {schema: {type:'object',properties:{saved_path:{type:'string'}}}}),
  () => agent('分析请求完整调用链，输出Markdown到D:/Desktop/code/learn-grok-build/docs/03-request-flow/README.md，包含输入入口、请求路由、Agent处理、模型调用、响应生成及时序图。返回{saved_path}', {schema: {type:'object',properties:{saved_path:{type:'string'}}}}),
])

log('文档撰写完成')
return { analyses: validAnalyses.length, docs: '架构|启动|请求流|AgentLoop|上下文|工具|工作区|会话|权限|扩展' }