<template>
  <el-config-provider :locale="locale === 'en' ? englishLocale : chineseLocale"><div class="workbench">
    <aside class="rail">
      <div class="brand" :aria-label="brand.name"><img class="brand-mark" :src="brand.icon" alt=""/><div class="brand-wordmark">{{brand.name}}<small>CLOUD OPERATIONS</small></div></div>
      <div class="nav-caption">{{t('工作空间')}}</div>
      <button v-for="item in navigation" :key="item.id" :class="['nav', {active: page===item.id}]" @click="page=item.id">
        <span class="nav-icon">{{item.icon}}</span>{{item.label}}<span v-if="page===item.id" class="nav-dot"></span>
      </button>
      <div class="rail-footer"><div class="status-dot"></div>{{t('本机单操作员模式')}}<p>{{t('只读分析 · 云资源无变更')}}</p></div>
    </aside>
    <main>
      <header>
        <div><span class="eyebrow">{{brand.name.toUpperCase()}} · CLOUD INTELLIGENCE</span><h1>{{navigation.find(n=>n.id===page)?.label}}</h1></div>
        <div class="environment-controls">
          <el-select v-model="locale" aria-label="Language / 语言" style="width:136px"><el-option value="zh" label="中文"/><el-option value="en" label="English"/></el-select>
          <el-select v-model="environment" @change="changeEnvironment" style="width:184px"><el-option v-for="e in environments" :key="e.id" :value="e.id" :label="t(e.name)"/></el-select>
          <el-select v-model="region" @change="refreshResources" style="width:176px"><el-option v-for="r in currentEnvironment?.regions || ['cn-beijing']" :key="r" :value="r" :label="r"/></el-select>
        </div>
      </header>
      <div class="source-strip"><span :class="['source-pill',environment==='demo'?'demo':'live']">{{environment==='demo'?t('演示数据'):t('阿里云只读数据')}}</span><span>{{t(currentEnvironment?.validation || '')}}</span><span class="right">{{t('时间显示：北京时间')}}</span></div>
      <el-alert v-if="error" :title="error" type="error" show-icon :closable="true" @close="error=''"/>
      <section v-if="environment==='aliyun' && !currentEnvironment?.configured && (page==='overview' || page==='analysis')" class="configuration-panel">
        <div class="configuration-icon">⌁</div><h2>{{t('连接你的阿里云环境')}}</h2><p>{{t('尚未配置只读凭据。当前没有加载任何演示资源。')}}</p>
        <div class="config-code">ALIBABA_CLOUD_ACCESS_KEY_ID<br/>ALIBABA_CLOUD_ACCESS_KEY_SECRET<br/><span>{{t('可选：ALIBABA_CLOUD_SECURITY_TOKEN')}}<br/>{{t('地域允许列表：ALIYUN_REGIONS')}}</span></div>
        <p>{{t('在服务端 agent/.env 填写后重启后端。内存监控需要实例安装云监控 Agent。')}}</p>
        <el-button @click="loadEnvironments">{{t('重新检查配置')}}</el-button>
      </section>
      <template v-else>
        <template v-if="page==='overview' || page==='analysis'">
          <div class="summary-grid">
            <div class="stat-card"><span>{{t('当前地域实例')}}</span><strong>{{resources.length}}<small>{{t('台')}}</small></strong><p>{{environment==='demo'?t('覆盖六类典型运维场景'):t('来自当前云账号与允许地域')}}</p></div>
            <div class="stat-card"><span>{{t('运行中')}}</span><strong>{{resources.filter(r=>r.status==='Running').length}}<small>{{t('台')}}</small></strong><p>{{t('停止实例不生成降配候选')}}</p></div>
            <div class="stat-card"><span>{{t('分析窗口')}}</span><strong>7<small>{{t('个完整 UTC 日')}}</small></strong><p>{{t('5 分钟粒度 · 监控完整度检查')}}</p></div>
            <div class="stat-card connection"><span>{{t('连接状态')}}</span><strong :class="connected?'good':'muted'">{{loading?t('检查中'):connected?t('已连接'):t('未连接')}}</strong><p>{{updatedAt?`${t('更新于')} ${formatTime(updatedAt)}`:t('刷新以获取资源')}}</p></div>
          </div>
          <div class="section-heading"><div><h2>{{page==='overview'?t('资源清单'):t('选择需要分析的实例')}}</h2><p>{{t('选择最多 20 台实例，生成可追溯的监控与成本分析报告。')}}</p></div><div><el-button :loading="loading" @click="refreshResources">{{t('刷新资源')}}</el-button><el-button type="primary" :disabled="!selected.length || creating || activeTask" @click="createAnalysis">{{activeTask?t('分析执行中'):`${t('分析已选')} (${selected.length})`}}</el-button></div></div>
          <div class="panel">
            <el-table :data="resources" row-key="id" @selection-change="(rows:Resource[])=>selected=rows.map(r=>r.id)" v-loading="loading">
              <el-table-column type="selection" width="45"/>
              <el-table-column :label="t('实例')" min-width="220"><template #default="{row}"><b>{{t(row.name)}}</b><div class="subtle mono">{{row.id}}</div></template></el-table-column>
              <el-table-column :label="t('规格')" min-width="175"><template #default="{row}">{{row.instance_type}}<div class="subtle">{{row.cpu}} vCPU / {{row.memory_gb}} GiB</div></template></el-table-column>
              <el-table-column :label="t('状态')" width="105"><template #default="{row}"><el-tag :type="row.status==='Running'?'success':'info'" effect="light">{{row.status==='Running'?t('运行中'):row.status}}</el-tag></template></el-table-column>
              <el-table-column :label="t('计费方式')" width="120"><template #default="{row}">{{row.spot?t('抢占式'):row.billing==='PostPaid'?t('按量付费'):t('包年包月')}}</template></el-table-column>
              <el-table-column :label="t('地域')" prop="region" min-width="120"/>
            </el-table>
            <el-empty v-if="!resources.length && !loading" :description="t('当前环境和地域没有可用实例')"/>
          </div>
          <div class="note-grid"><div><b>{{t('数据驱动的建议')}}</b><p>{{t('检查均值、峰值与覆盖率。监控不足时明确标出缺失，避免不充分的降配建议。')}}</p></div><div><b>{{t('费用估算有边界')}}</b><p>{{environment==='demo'?t('当前使用示例价格，不是真实云报价。'):t('仅普通按量付费实例支持计算规格原价对比。')}} {{t('不包含磁盘、网络和优惠。')}}</p></div></div>
        </template>
        <template v-if="page==='history'">
          <div class="section-heading"><div><h2>{{t('分析记录')}}</h2><p>{{t('保留规则版本、资源快照与执行证据，支持查看和重新运行。')}}</p></div><el-button @click="refreshTasks">{{t('刷新记录')}}</el-button></div>
          <div class="panel"><el-table :data="tasks" @row-click="(row:Task)=>openReport(row.id)" class="clickable">
            <el-table-column :label="t('任务')" min-width="180"><template #default="{row}"><b>{{row.resource_ids.length}} {{t('实例分析')}}</b><div class="subtle mono">{{row.id.slice(0,8)}}</div></template></el-table-column>
            <el-table-column :label="t('来源')" min-width="140"><template #default="{row}">{{t(row.source)}}</template></el-table-column><el-table-column :label="t('地域')" prop="region" width="130"/>
            <el-table-column :label="t('状态')" width="130"><template #default="{row}"><el-tag :type="statusType(row.status)">{{statusLabel(row.status)}}</el-tag></template></el-table-column>
            <el-table-column :label="t('创建时间')" min-width="170"><template #default="{row}">{{formatTime(row.created_at)}}</template></el-table-column>
          </el-table><el-empty v-if="!tasks.length" :description="t('尚无分析记录，从资源总览开始一次分析')"/></div>
        </template>
        <div v-if="page==='chat'" class="chat-panel"><ChatPanel :key="`${environment}:${region}`" :environment="environment" :region="region" @report="openReport"/></div>
      </template>
      <el-drawer v-model="showReport" size="min(860px,95vw)" :title="t('云资源分析报告')" @closed="stopPolling">
        <template v-if="report">
          <div class="report-heading"><el-tag :type="report.environment==='demo'?'warning':'success'">{{t(report.source)}}</el-tag><el-tag :type="statusType(report.status)">{{statusLabel(report.status)}}</el-tag><el-button size="small" @click="downloadReport">{{t('下载 Markdown')}}</el-button><el-button size="small" :disabled="!terminal(report.status)" @click="rerun">{{t('重新分析')}}</el-button></div>
          <p class="subtle">{{report.region}} · {{t('规则')}} {{report.rule_version}} · {{formatTime(report.created_at)}}</p>
          <p v-if="report.window_start" class="subtle">{{t('窗口：')}}{{formatTime(report.window_start)}} — {{formatTime(report.window_end || '')}}{{t('（不含结束时刻）')}}</p>
          <el-alert v-if="!terminal(report.status)" :title="t('正在采集监控与生成报告，可在分析记录中继续查看。')" type="info" :closable="false"/>
          <el-alert v-if="report.error" :title="t(report.error)" type="error" :closable="false"/>
          <article v-for="(result,index) in report.results" :key="index" class="result-card">
            <template v-if="result.resource && result.metrics">
              <div class="result-heading"><h3>{{t(result.resource.name)}}</h3><el-tag :type="result.diagnosis==='low_utilization'?'success':result.diagnosis==='peak_risk'?'danger':'info'">{{diagnosisLabel(result.diagnosis)}}</el-tag></div>
              <p class="subtle mono">{{result.resource.id}} · {{result.resource.instance_type}}</p>
              <div class="metric-grid"><div v-for="metric in ['cpu','memory'] as const" :key="metric"><label>{{metric==='cpu'?'CPU':t('内存')}}</label><strong>{{number(result.metrics[metric].average)}}<small v-if="result.metrics[metric].average!==null">%</small></strong><el-progress :percentage="result.metrics[metric].maximum || 0" :show-text="false" :color="(result.metrics[metric].maximum||0)>=80?'#e09355':'#4f8277'"/><p>{{t('最大')}} {{number(result.metrics[metric].maximum)}}{{result.metrics[metric].maximum===null?'':'%'}} · {{t('均值覆盖')}} {{(result.metrics[metric].coverage*100).toFixed(1)}}% · {{t('峰值覆盖')}} {{(result.metrics[metric].peak_coverage*100).toFixed(1)}}%</p></div></div>
              <div v-if="result.candidate" class="candidate"><b>{{t('待核验候选：')}}{{result.candidate.id}}</b><p>{{result.candidate.cpu}} vCPU / {{result.candidate.memory_gb}} GiB · {{t('容量减半后的线性负载估算')}}</p></div>
              <div v-if="result.savings" class="saving"><span>{{t('月度等价估算差额')}}</span><strong>{{result.savings.currency}} {{result.savings.monthly_equivalent_saving.toFixed(2)}}</strong><p>{{t(result.savings.source)}} · {{t('按 730 小时换算')}}</p><p>{{t(result.savings.scope)}}</p></div><p v-else class="subtle">{{t(result.pricing_note)}}</p>
              <ul class="risks"><li v-for="risk in result.risks" :key="risk">{{t(risk)}}</li></ul>
            </template><el-alert v-else :title="`${result.resource_id}: ${t(result.error || '')}`" type="error" :closable="false"/>
          </article>
          <el-collapse><el-collapse-item :title="t('模型辅助解释（以结构化规则结论为准）')" name="explanation"><p v-if="locale==='en' && report.explanation && report.language !== 'en'" class="subtle">{{t('原文解释（中文）')}}</p><p>{{report.explanation || (report.explanation_status==='pending'?t('正在生成'):t('解释未生成；规则报告仍可使用'))}}</p></el-collapse-item></el-collapse>
          <h3 class="trace-title">{{t('执行步骤与数据来源')}}</h3>
          <div v-for="(step,index) in report.steps || []" :key="index" class="trace-row"><span :class="['trace-dot',step.status==='failed'?'failed':'']"></span><div><b>{{toolLabel(step.tool)}}</b><p>{{step.source==='demo'?t('演示数据'):t('阿里云')}} · {{step.resource_id || t('任务级步骤')}} <span v-if="step.error">· {{t(step.error)}}</span></p></div><span>{{step.duration_ms}} ms</span></div>
        </template>
      </el-drawer>
    </main>
  </div>
</el-config-provider>
</template>

<script setup lang="ts">
import { brand } from './brand'
import { locale, t } from './i18n'
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import englishLocale from 'element-plus/es/locale/lang/en'
import chineseLocale from 'element-plus/es/locale/lang/zh-cn'
import ChatPanel from './ChatPanel.vue'
interface Environment {id:string;name:string;configured:boolean;regions:string[];validation:string}
interface Resource {id:string;name:string;instance_type:string;cpu:number;memory_gb:number;region:string;status:string;billing:string;spot:boolean}
interface Metric {average:number|null;maximum:number|null;coverage:number;peak_coverage:number}
interface Result {resource?:Resource;resource_id?:string;error?:string;metrics?:{cpu:Metric;memory:Metric};diagnosis:string;risks:string[];candidate?:{id:string;cpu:number;memory_gb:number};savings?:{currency:string;monthly_equivalent_saving:number;source:string;scope:string};pricing_note:string}
interface Step {tool:string;source:string;resource_id?:string;status:string;duration_ms:number;error?:string}
interface Task {id:string;environment:string;region:string;source:string;status:string;resource_ids:string[];created_at:string;rule_version:string;window_start?:string;window_end?:string;results:Result[];steps?:Step[];error?:string;explanation?:string;explanation_status:string;language?:string}
const navigation=computed(()=>[{id:'overview',label:t('资源总览'),icon:'◫'},{id:'analysis',label:t('成本分析'),icon:'↗'},{id:'history',label:t('分析记录'),icon:'≡'},{id:'chat',label:t('智能助手'),icon:'✧'}])
const page=ref('overview'),environment=ref('demo'),region=ref('cn-beijing'),error=ref('')
const environments=ref<Environment[]>([]),resources=ref<Resource[]>([]),tasks=ref<Task[]>([]),selected=ref<string[]>([])
const loading=ref(false),creating=ref(false),connected=ref(false),updatedAt=ref(''),showReport=ref(false),report=ref<Task|null>(null)
const currentEnvironment=computed(()=>environments.value.find(e=>e.id===environment.value))
const activeTask=computed(()=>tasks.value.some(t=>t.environment===environment.value&&!terminal(t.status)))
let timer:ReturnType<typeof setTimeout>|undefined
let resourceRequest=0
let wantedReport=''
let taskTimer:ReturnType<typeof setTimeout>|undefined
async function api<T>(path:string,options:RequestInit={}):Promise<T>{
 const response=await fetch('/api'+path,{...options,headers:{'Content-Type':'application/json',...options.headers}})
 if(!response.ok){const data=await response.json();throw new Error(typeof data.detail==='string'?t(data.detail):t('请求参数或服务状态不正确'))}
 return response.json()
}
const terminal=(status:string)=>['succeeded','partial','failed','interrupted'].includes(status)
const statusLabel=(s:string)=>({queued:t('排队中'),running:t('执行中'),succeeded:t('完成'),partial:t('部分完成'),failed:t('失败'),interrupted:t('重启中断')}[s] || s)
const statusType=(s:string):'success'|'warning'|'danger'|'info'=>s==='succeeded'?'success':s==='partial'?'warning':['failed','interrupted'].includes(s)?'danger':'info'
const diagnosisLabel=(s:string)=>({low_utilization:t('低利用率候选'),normal:t('正常负载'),peak_risk:t('峰值风险'),insufficient_data:t('数据不足'),stopped:t('实例已停止')}[s] || s)
const toolLabel=(s:string)=>({list_resources:t('查询资源'),get_monitoring:t('读取监控'),assess_utilization:t('执行规则分析'),list_instance_types:t('查询候选规格'),quote_current:t('查询当前规格价格'),quote_candidate:t('查询候选价格'),model_explanation:t('生成辅助解释')}[s] || s)
const formatTime=(s:string)=>s?new Date(s).toLocaleString(locale.value === 'en' ? 'en-GB' : 'zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'—'
const number=(n:number|null)=>n===null?t('不可用'):n.toFixed(1)
async function loadEnvironments(){try{environments.value=await api<Environment[]>('/environments');await refreshResources()}catch(e){error.value=String(e)}}
async function refreshResources(){
 const request=++resourceRequest;loading.value=true;error.value='';connected.value=false;resources.value=[];selected.value=[]
 if(!currentEnvironment.value?.configured){loading.value=false;return}
 try{const data=await api<Resource[]>(`/resources?environment=${environment.value}&region=${encodeURIComponent(region.value)}`);if(request===resourceRequest){resources.value=data;connected.value=true;updatedAt.value=new Date().toISOString()}}
 catch(e){if(request===resourceRequest)error.value=String(e)}finally{if(request===resourceRequest)loading.value=false}
}
function changeEnvironment(){region.value=currentEnvironment.value?.regions[0]||'cn-beijing';showReport.value=false;refreshResources()}
async function refreshTasks(){if(taskTimer)clearTimeout(taskTimer);try{tasks.value=await api<Task[]>('/analyses');if(tasks.value.some(t=>!terminal(t.status)))taskTimer=setTimeout(refreshTasks,3000)}catch(e){error.value=String(e)}}
async function createAnalysis(){creating.value=true;try{const task=await api<Task>('/analyses',{method:'POST',body:JSON.stringify({environment:environment.value,region:region.value,instance_ids:selected.value,language:locale.value})});await refreshTasks();await openReport(task.id)}catch(e){error.value=String(e)}finally{creating.value=false}}
function stopPolling(){wantedReport='';if(timer)clearTimeout(timer)}
async function openReport(id:string){stopPolling();wantedReport=id;showReport.value=true;report.value=null;await poll(id)}
async function poll(id:string){try{const task=await api<Task>(`/analyses/${id}`);if(!showReport.value||wantedReport!==id)return;report.value=task;if(!terminal(task.status))timer=setTimeout(()=>poll(id),1500);else await refreshTasks()}catch(e){error.value=String(e)}}
function downloadReport(){if(report.value)window.open(`/api/analyses/${report.value.id}/report.md?lang=${locale.value}`,'_blank','noopener')}
async function rerun(){if(!report.value)return;try{const task=await api<Task>('/analyses',{method:'POST',body:JSON.stringify({environment:report.value.environment,region:report.value.region,instance_ids:report.value.resource_ids,language:locale.value})});await openReport(task.id)}catch(e){ElMessage.error(String(e))}}
onMounted(async()=>{await loadEnvironments();await refreshTasks()})
onUnmounted(()=>{stopPolling();if(taskTimer)clearTimeout(taskTimer)})
</script>

<style scoped>
.workbench{display:flex;min-height:100vh;font-size:16px;background:#f5f7f8;color:#203036;font-family:Inter,-apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif}.rail{width:260px;flex:none;background:#142a2d;color:#c5d4d1;padding:32px 18px;position:fixed;top:0;bottom:0;display:flex;flex-direction:column}.brand{display:flex;align-items:center;gap:12px;font-size:22px;font-weight:650;color:#fff;margin-bottom:54px}.brand small{display:block;font-size:10px;letter-spacing:1.4px;color:#86a39c;margin-top:5px}.brand-mark{width:42px;height:42px;flex:none;display:block}.brand-wordmark{min-width:0;letter-spacing:-.4px}.logo{width:40px;height:40px;border:1px solid #6d9b8f;border-radius:12px;display:grid;place-content:center;color:#d3ebdc;font-size:20px;position:relative}.logo span{position:absolute;font-size:12px;right:7px;bottom:5px;color:#82b7a4}.nav-caption{font-size:14px;letter-spacing:2px;color:#718e87;margin:0 18px 15px}.nav{display:flex;align-items:center;gap:14px;width:100%;background:none;color:#aebfbc;border:0;text-align:left;padding:15px 17px;margin:3px 0;border-radius:9px;font-size:16px;cursor:pointer}.nav.active{background:#26443f;color:#eef8f1}.nav-icon{font-size:22px;line-height:1}.nav-dot{width:5px;height:5px;background:#9dd5b3;border-radius:50%;margin-left:auto}.rail-footer{margin-top:auto;padding:18px 12px 0;border-top:1px solid #31433f;font-size:15px}.rail-footer p{font-size:14px;color:#7c9891;margin-top:8px}.status-dot{display:inline-block;background:#a6c8a2;width:6px;height:6px;border-radius:50%;margin-right:8px}main{margin-left:260px;padding:34px 40px;width:calc(100% - 260px);min-width:0}header{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:16px;margin-bottom:24px}.eyebrow{font-size:12px;letter-spacing:2px;color:#7f9690;font-weight:600}h1{font-size:30px;font-weight:600;margin:7px 0 0;letter-spacing:-.5px}.environment-controls{display:flex;gap:10px;flex-wrap:wrap;max-width:100%}.source-strip{display:flex;flex-wrap:wrap;align-items:center;gap:12px;font-size:15px;color:#7a898a;margin-bottom:28px}.source-pill{border-radius:5px;padding:5px 9px;font-weight:600}.demo{background:#f2e8d6;color:#96763e}.live{background:#dfebe5;color:#38735c}.right{margin-left:auto}.summary-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin-bottom:34px}.stat-card{min-width:0;padding:23px;background:#fff;border:1px solid #e2e9e7;border-radius:12px}.stat-card>span{font-size:15px;color:#7e8b8a}.stat-card strong{display:block;font-size:36px;font-weight:550;margin-top:14px;line-height:1.2}.stat-card small{font-size:15px;font-weight:400;margin-left:8px;color:#7b8d88}.stat-card p{font-size:14px;color:#93a29e;margin:13px 0 0}.connection strong{font-size:clamp(18px,2.2vw,26px);overflow-wrap:anywhere;margin-top:19px}.good{color:#497e65}.muted{color:#879390}.section-heading{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px;gap:12px}h2{font-size:20px;font-weight:600;margin:0}.section-heading p{font-size:15px;color:#8a9697;margin:7px 0 0}.panel{border:1px solid #e1e8e5;background:#fff;border-radius:12px;padding:10px 18px 15px;overflow:hidden}.subtle{font-size:14px;color:#879695;margin:7px 0}.mono{font-family:ui-monospace,monospace;font-size:14px}.note-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:23px}.note-grid>div{padding:21px 24px;border:1px solid #e0e8e4;background:#edf3ef;border-radius:11px}.note-grid b{font-size:15px;font-weight:600;color:#597a68}.note-grid p{font-size:15px;line-height:1.8;color:#83968c;margin:7px 0 0}.configuration-panel{max-width:750px;background:#fff;border:1px solid #e1e8e5;border-radius:14px;padding:44px;margin:35px auto}.configuration-panel p{font-size:16px;line-height:1.8;color:#899793}.configuration-icon{font-size:38px;color:#4e806c;margin-bottom:16px}.config-code{background:#f1f5f3;padding:20px;font-family:monospace;line-height:2;font-size:15px;border-radius:9px;margin:20px 0;color:#43695b}.config-code span{color:#87988f}.chat-panel{height:calc(100vh - 188px);border:1px solid #e1e8e5;border-radius:12px;overflow:hidden}.report-heading{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.result-card{border:1px solid #e0e8e3;border-radius:12px;padding:20px;margin:20px 0}.result-heading{display:flex;justify-content:space-between;align-items:center}.result-heading h3{margin:0;font-size:19px}.metric-grid{display:grid;grid-template-columns:1fr 1fr;gap:25px;background:#f5f8f6;padding:18px;border-radius:8px;margin:18px 0}.metric-grid label{display:block;font-size:15px;color:#7f9287}.metric-grid strong{display:block;font-size:30px;font-weight:500;margin:8px 0}.metric-grid small{font-size:16px}.metric-grid p{font-size:14px;color:#819286;margin-top:8px}.candidate{background:#e9f1ea;border-radius:8px;padding:16px;color:#4a7159;font-size:16px}.candidate p{font-size:14px;margin:6px 0 0}.saving{padding:18px 0}.saving span{font-size:15px;color:#7e9388}.saving strong{display:block;font-size:28px;color:#3d7155;margin:6px 0}.saving p{font-size:14px;color:#8c998e}.risks{font-size:15px;line-height:1.9;color:#8d7a58;padding-left:18px}.trace-title{margin-top:25px;font-size:15px}.trace-row{display:flex;gap:13px;align-items:center;border-bottom:1px solid #edf1ee;padding:15px 0;font-size:15px}.trace-row>span:last-child{margin-left:auto;color:#8b9991;font-family:monospace}.trace-dot{width:7px;height:7px;background:#6b9e82;border-radius:50%;flex-shrink:0}.trace-dot.failed{background:#cb8a62}.trace-row p{font-size:14px;color:#9aa69d;margin:5px 0 0}.clickable :deep(.el-table__row){cursor:pointer}:deep(.el-button--primary){--el-button-bg-color:#356756;--el-button-border-color:#356756;--el-button-hover-bg-color:#477b68;--el-button-hover-border-color:#477b68}:deep(.el-table th.el-table__cell){background:#fafcfb;color:#8d9c94;font-size:14px;font-weight:500}:deep(.el-table td.el-table__cell){padding:17px 0;font-size:15px;color:#526c60}:deep(.el-drawer__title){font-size:21px;font-weight:600;color:#2a4435}:deep(.el-alert){margin-bottom:15px}@media(max-width:1100px){.rail{width:240px}main{margin-left:240px;width:calc(100% - 240px);padding:26px 22px}.summary-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.section-heading{align-items:flex-start}}@media(max-width:720px){.rail{width:70px;padding:25px 10px}.brand>div:last-child,.nav-caption,.nav-dot,.rail-footer{display:none}.brand{margin-bottom:25px}.nav{font-size:0;padding:15px 10px}.nav-icon{font-size:22px}main{margin-left:70px;width:calc(100% - 70px);padding:22px 14px}header{align-items:flex-start;gap:15px;flex-direction:column}.summary-grid{gap:10px}.stat-card{padding:16px}.note-grid{grid-template-columns:1fr}.right{display:none}.section-heading{flex-direction:column}}
</style>
