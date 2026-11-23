import { Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { EntityPage } from './pages/Entity'
import { ExplainPage } from './pages/Explain'
import { NetworkPage } from './pages/Network'
import { Placeholder } from './pages/Placeholder'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route
          index
          element={<Placeholder title="Bảng tin" subtitle="Tin mới nhất về các chủ đề đang theo dõi" plan={['Tin báo chí và video mới sau 21/10/2026', 'Thực thể và quan hệ mới phát hiện trong từng tin', 'Lọc theo nguồn, thời gian, chủ đề']} />}
        />
        <Route
          path="watch"
          element={<Placeholder title="Theo dõi & cảnh báo" subtitle="Chọn nghệ sĩ, công ty, cộng đồng hoặc chương trình để nhận cảnh báo" plan={['Cảnh báo bài mới, hợp tác mới, phát hành mới, tranh chấp', 'Theo dõi cả hàng xóm 1–2 bước trên đồ thị', 'Đột biến lượng nhắc so với 4 tuần trước']} />}
        />
        <Route path="trends" element={<Placeholder title="Xu hướng" subtitle="Nghệ sĩ, bài hát, cộng đồng đang lên" plan={['Số lần được nhắc theo ngày', 'Gộp theo cộng đồng', 'Chủ đề nóng']} />} />
        <Route path="ask" element={<Placeholder title="Hỏi đáp" subtitle="Hỏi đáp nhiều bước bằng GraphRAG và SLM chạy cục bộ" plan={['Liên kết thực thể trong câu hỏi', 'Truy xuất đồ thị con tối đa 3 bước + câu bằng chứng', 'Trả lời kèm nguồn và đồ thị con']} />} />
        <Route path="explain" element={<ExplainPage />} />
        <Route path="network" element={<NetworkPage />} />
        <Route path="entity/:id" element={<EntityPage />} />
      </Route>
    </Routes>
  )
}
