import { Card, PageHeader } from '../components/ui'

export function Placeholder({ title, subtitle, plan }: { title: string; subtitle: string; plan: string[] }) {
  return (
    <div className="space-y-6">
      <PageHeader title={title} subtitle={subtitle} />
      <Card title="Đang xây dựng" subtitle="Màn hình này cần luồng tin mới sau khi chạy làm giàu dữ liệu">
        <ul className="list-disc space-y-1 pl-5 text-sm text-slate-600">
          {plan.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      </Card>
    </div>
  )
}
