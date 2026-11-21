import type { components } from './openapi.generated'
type Models = components['schemas']
export type User = Models['Listener']
export type Preferences = Models['PreferenceView']
export type Voice = Models['VoiceView']
export type Schedule = Models['ScheduleView']
export type Costs = Models['CostReport']
export type Source = Models['SourceInfo']
export type Topic = Models['TopicInfo']
export type Article = Models['ArticleInfo']
export type Evidence = Models['EvidenceInfo']
export type Fact = Models['FactInfo']
export type Story = Models['StoryInfo'] & {
  selection?: {
    score: number
    reasons: string[]
    adjustments: string[]
    factors: Record<string, { value: number; weight: number; contribution: number }>
  }
}
export type StoryDetail = Models['Detail']
export type StoryPage = Models['Page']
export type Citation = Pick<
  Models['Citation'],
  'article_id' | 'source' | 'url' | 'excerpt'
> &
  Partial<Pick<Models['Citation'], 'title' | 'is_synthetic'>>
export type Segment = Models['Segment']
export type Briefing = Models['BriefingView']
export type BriefingDetail = Models['BriefingDetail']
export type Message = Models['MessageView']
export type ResearchResult = Models['ResearchResult']
export type Conversation = Models['ConversationView']
