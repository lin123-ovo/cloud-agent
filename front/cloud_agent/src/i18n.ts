import { ref, watch } from 'vue'
import english from './locales/en.json'
import { brand } from './brand'
export type Language = 'zh' | 'en'
const saved = localStorage.getItem('cloudagent-language')
const queryLanguage = new URLSearchParams(location.search).get('lang')
export const locale = ref<Language>(queryLanguage === 'en' || (queryLanguage !== 'zh' && saved === 'en') ? 'en' : 'zh')
const dictionary: Record<string, string> = english
export function t(text: string): string {
  if (locale.value === 'zh' || !text) return text
  if (dictionary[text]) return dictionary[text]
  // Unrecognized user-defined names and source text retain their original spelling.
  return text
}
watch(locale, value => {
  localStorage.setItem('cloudagent-language', value)
  const url = new URL(location.href)
  url.searchParams.set('lang', value)
  history.replaceState(null, '', url)
  document.documentElement.lang = value === 'en' ? 'en' : 'zh-CN'
  document.title = value === 'en' ? `${brand.name} · Cloud operations workspace` : `${brand.name} · 云资源工作台`
}, { immediate: true })
