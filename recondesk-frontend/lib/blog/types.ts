export interface Author {
  name: string;
  role: string;
  avatarUrl?: string;
}

export interface BlogPost {
  slug: string;
  title: string;
  excerpt: string;
  publishedAt: string;
  readTime: string;
  category: "ITC Optimization" | "GST Compliance" | "Tax Tech" | "CA Practice";
  author: Author;
  tags: string[];
  coverGradient: string;
  featured?: boolean;
  content: string;
}
