import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap, type Schemas } from './client'
import { keys } from './hooks'

export type Catalog = Schemas['Catalog']
export type CatalogPipeline = Schemas['CatalogPipeline']
export type CatalogRetrieval = Schemas['CatalogRetrieval']
export type CatalogProfile = Schemas['CatalogProfile']
export type CatalogPrompt = Schemas['CatalogPrompt']
export type CatalogField = Schemas['CatalogField']
export type CatalogFieldSet = Schemas['CatalogFieldSet']
export type CatalogProvider = Schemas['CatalogProvider']
export type CatalogModel = Schemas['CatalogModel']
export type CatalogDecomposition = Schemas['CatalogDecomposition']
export type CatalogIndex = Schemas['CatalogIndex']
export type VersionRef = Schemas['VersionRef']

const data = async <T,>(call: Parameters<typeof unwrap<T>>[0]) => (await unwrap(call)).data
const done = async (call: Parameters<typeof unwrap<unknown>>[0]) => {
  await unwrap(call)
}

/** Every configuration write. Paths are by name for named rows, by id for models and fields. */
export const configApi = {
  createPipeline: (body: Schemas['PipelineCreate']) => data(api.POST('/api/v1/config/pipelines', { body })),
  updatePipeline: ({ name, body }: { name: string; body: Schemas['PipelineUpdate'] }) =>
    data(api.PATCH('/api/v1/config/pipelines/{name}', { params: { path: { name } }, body })),
  deletePipeline: (name: string) => done(api.DELETE('/api/v1/config/pipelines/{name}', { params: { path: { name } } })),
  setDefaultPipeline: (name: string) =>
    data(api.POST('/api/v1/config/pipelines/{name}/default', { params: { path: { name } } })),

  createRetrieval: (body: Schemas['RetrievalCreate']) => data(api.POST('/api/v1/config/retrievals', { body })),
  updateRetrieval: ({ name, body }: { name: string; body: Schemas['RetrievalUpdate'] }) =>
    data(api.PATCH('/api/v1/config/retrievals/{name}', { params: { path: { name } }, body })),
  deleteRetrieval: (name: string) => done(api.DELETE('/api/v1/config/retrievals/{name}', { params: { path: { name } } })),

  createProfile: (body: Schemas['ProfileCreate']) => data(api.POST('/api/v1/config/profiles', { body })),
  updateProfile: ({ name, body }: { name: string; body: Schemas['ProfileUpdate'] }) =>
    data(api.PATCH('/api/v1/config/profiles/{name}', { params: { path: { name } }, body })),
  deleteProfile: (name: string) => done(api.DELETE('/api/v1/config/profiles/{name}', { params: { path: { name } } })),

  createDecomposition: (body: Schemas['DecompositionCreate']) => data(api.POST('/api/v1/config/decompositions', { body })),
  deleteDecomposition: (name: string) =>
    done(api.DELETE('/api/v1/config/decompositions/{name}', { params: { path: { name } } })),
  createIndex: (body: Schemas['IndexCreate']) => data(api.POST('/api/v1/config/indexes', { body })),
  deleteIndex: (name: string) => done(api.DELETE('/api/v1/config/indexes/{name}', { params: { path: { name } } })),

  createPrompt: (body: Schemas['PromptCreate']) => data(api.POST('/api/v1/config/prompts', { body })),
  createPromptVersion: ({ name, body }: { name: string; body: Schemas['PromptVersionCreate'] }) =>
    data(api.POST('/api/v1/config/prompts/{name}/versions', { params: { path: { name } }, body })),

  createField: ({ fieldSet, body }: { fieldSet: VersionRef; body: Schemas['FieldCreate'] }) =>
    data(
      api.POST('/api/v1/config/field-sets/{name}/{version}/fields', {
        params: { path: { name: fieldSet.name, version: fieldSet.version } },
        body,
      }),
    ),
  updateField: ({ id, body }: { id: string; body: Schemas['FieldUpdate'] }) =>
    data(api.PATCH('/api/v1/config/fields/{field_id}', { params: { path: { field_id: id } }, body })),

  updateProvider: ({ key, body }: { key: string; body: Schemas['ProviderUpdate'] }) =>
    data(api.PATCH('/api/v1/config/providers/{key}', { params: { path: { key } }, body })),
  createModel: ({ key, body }: { key: string; body: Schemas['ModelCreate'] }) =>
    data(api.POST('/api/v1/config/providers/{key}/models', { params: { path: { key } }, body })),
  updateModel: ({ id, body }: { id: string; body: Schemas['ModelUpdate'] }) =>
    data(api.PATCH('/api/v1/config/models/{model_id}', { params: { path: { model_id: id } }, body })),
}

export function useCatalog() {
  return useQuery({
    queryKey: keys.catalog,
    queryFn: async () => (await unwrap(api.GET('/api/v1/config/catalog'))).data,
  })
}

/** A configuration write; afterwards the catalog and the new-run dialog's pipelines are fetched again. */
export function useConfigWrite<TArgs, TOut>(write: (args: TArgs) => Promise<TOut>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: write,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.catalog })
      qc.invalidateQueries({ queryKey: keys.pipelines })
    },
  })
}
