import type { Metadata } from "next";
import "./globals.css";
export const metadata:Metadata={title:"دیدبان بازار | تحلیل و نقاط معاملاتی",description:"داشبورد پایش فارکس و رمزارز با دادهٔ بازار، شروط ورود و مدیریت ریسک",icons:{icon:"/favicon.svg"}};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="fa" dir="rtl"><body>{children}</body></html>;}
