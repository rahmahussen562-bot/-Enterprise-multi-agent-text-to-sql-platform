import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { DirectionProvider } from '@radix-ui/react-direction';
import '@fontsource-variable/inter';
import './style.css';
import { Landing } from './components/Landing';
import { Login } from './components/Login';
import { Workspace } from './components/Workspace';
import type { Session } from './api/client';
import { en, ar, type Language, type Translator } from './i18n';
function App(){
  const [language,setLanguage]=useState<Language>(()=>localStorage.getItem('sentinel-language')==='ar'?'ar':'en');
  const [session,setSession]=useState<Session|null>(null),[login,setLogin]=useState(false);
  const t:Translator=key=>(language==='en'?en:ar)[key];
  useEffect(()=>{document.documentElement.lang=language;document.documentElement.dir=language==='ar'?'rtl':'ltr';localStorage.setItem('sentinel-language',language);},[language]);
  const change=()=>setLanguage(value=>value==='en'?'ar':'en');
  return <DirectionProvider dir={language==='ar'?'rtl':'ltr'}>{session?<Workspace key={session.session.user_id} session={session} t={t} language={language} onLanguage={change} onLogout={()=>setSession(null)}/>:<Landing t={t} language={language} onLanguage={change} onLogin={()=>setLogin(true)}/>}<Login open={login} onOpenChange={setLogin} onSession={setSession} t={t}/></DirectionProvider>;
}
createRoot(document.getElementById('root')!).render(<App/>);
