import { useSearchParams } from 'react-router'
import { useCatalog } from '@/api/config'
import { ProblemAlert } from '@/components/ProblemAlert'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { FieldsTab } from '@/features/config/FieldsTab'
import { ModelsTab } from '@/features/config/ModelsTab'
import { PipelinesTab } from '@/features/config/PipelinesTab'
import { PromptsTab } from '@/features/config/PromptsTab'
import { RetrievalsTab } from '@/features/config/RetrievalsTab'
import { StorageTab } from '@/features/config/StorageTab'

const TABS = [
  { value: 'pipelines', label: 'Pipelines', Tab: PipelinesTab },
  { value: 'retrievals', label: 'RAG configs', Tab: RetrievalsTab },
  { value: 'fields', label: 'Fields', Tab: FieldsTab },
  { value: 'models', label: 'Models & profiles', Tab: ModelsTab },
  { value: 'prompts', label: 'Prompts', Tab: PromptsTab },
  { value: 'storage', label: 'Decomposition & index', Tab: StorageTab },
]

/** Configuration stored in the database. Runs use a snapshot, so edits only affect runs queued afterwards. */
export function ConfigPage() {
  const catalog = useCatalog()
  const [params, setParams] = useSearchParams()
  const tab = TABS.some((t) => t.value === params.get('tab')) ? params.get('tab')! : 'pipelines'

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">Configuration</h1>
        <p className="text-sm text-muted-foreground">
          Changes apply to runs queued afterwards. Queued and finished runs keep the configuration they started with.
        </p>
      </div>
      <ProblemAlert error={catalog.error} />
      {catalog.isPending && <Skeleton className="h-64" />}
      {catalog.data && (
        <Tabs value={tab} onValueChange={(v) => setParams({ tab: v })}>
          <TabsList className="flex-wrap">
            {TABS.map((t) => (
              <TabsTrigger key={t.value} value={t.value}>
                {t.label}
              </TabsTrigger>
            ))}
          </TabsList>
          {TABS.map(({ value, Tab }) => (
            <TabsContent key={value} value={value} className="pt-3">
              <Tab catalog={catalog.data} />
            </TabsContent>
          ))}
        </Tabs>
      )}
    </div>
  )
}
