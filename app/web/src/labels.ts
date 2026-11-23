export const TYPE_LABEL: Record<string, string> = {
  Person: 'Nghệ sĩ',
  Group: 'Nhóm nhạc',
  Song: 'Bài hát',
  Album: 'Album',
  Company: 'Công ty',
  Show: 'Chương trình',
  Event: 'Sự kiện',
  Brand: 'Thương hiệu',
}

export const TYPE_COLOR: Record<string, string> = {
  Person: '#6366f1',
  Group: '#8b5cf6',
  Song: '#0ea5e9',
  Album: '#14b8a6',
  Company: '#f59e0b',
  Show: '#ec4899',
  Event: '#f43f5e',
  Brand: '#84cc16',
}

export const RELATION_LABEL: Record<string, string> = {
  PERFORMED: 'trình bày',
  FEATURED_ON: 'góp giọng (feat.)',
  COMPOSED: 'sáng tác',
  PRODUCED: 'sản xuất',
  RELEASED_BY: 'phát hành bởi',
  TRACK_OF: 'thuộc album',
  MEMBER_OF: 'thành viên của',
  CONTESTANT_ON: 'thí sinh',
  JUDGE_ON: 'giám khảo/HLV',
  PERFORMED_AT: 'biểu diễn tại',
  ORGANIZED_BY: 'tổ chức bởi',
  AMBASSADOR_OF: 'đại sứ/quảng cáo',
  COLLABORATED_WITH: 'hợp tác với',
  DISPUTED_WITH: 'tranh chấp với',
}

export const fmt = (v: unknown, digits = 0) =>
  typeof v === 'number' ? v.toLocaleString('vi-VN', { maximumFractionDigits: digits, minimumFractionDigits: digits }) : String(v ?? '–')
