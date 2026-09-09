import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { api } from '../lib/api.js';

const T = {
  en: { hi: (n) => `Hi ${n}, this is your neighbors checking in.`, q: 'Are you okay right now?', ok: "I'm OK", help: 'I need help', note: 'Anything we should know? (optional)', send: 'Send', thanksOk: 'Thank you. We are glad you are safe.', thanksHelp: 'Help is on the way. A neighbor will contact you very soon.', stay: 'Stay in the coolest room, drink water, and call 911 if you feel confused, dizzy, or stop sweating.', already: 'You already checked in. Thank you.' },
  es: { hi: (n) => `Hola ${n}, somos sus vecinos y queremos saber cómo está.`, q: '¿Está bien en este momento?', ok: 'Estoy bien', help: 'Necesito ayuda', note: '¿Algo que debamos saber? (opcional)', send: 'Enviar', thanksOk: 'Gracias. Nos alegra que esté a salvo.', thanksHelp: 'La ayuda va en camino. Un vecino le contactará muy pronto.', stay: 'Quédese en el cuarto más fresco, tome agua y llame al 911 si se siente confundido, mareado o deja de sudar.', already: 'Ya se registró. Gracias.' },
};

export default function Checkin() {
  const { token } = useParams();
  const [info, setInfo] = useState(null);
  const [err, setErr] = useState('');
  const [lang, setLang] = useState('en');
  const [choice, setChoice] = useState('');
  const [note, setNote] = useState('');
  const [done, setDone] = useState('');

  useEffect(() => {
    api.checkin(token).then((d) => { setInfo(d); setLang(d.language === 'es' ? 'es' : 'en'); if (['ok', 'needs_help', 'escalated'].includes(d.status)) setDone(d.status); }).catch((e) => setErr(e.message));
  }, [token]);

  const t = T[lang];
  const submit = async (status) => {
    setChoice(status);
    try {
      await api.submitCheckin(token, { status, note });
      setDone(status);
    } catch (e) { setErr(e.message); }
  };

  if (err) return <div className="checkin"><div className="card"><h1>This link is not valid.</h1><p>Please contact your block captain.</p></div></div>;
  if (!info) return <div className="checkin"><div className="card"><p>…</p></div></div>;

  return (
    <div className="checkin">
      <div className="card">
        <div className="lang">
          <button className={lang === 'en' ? 'on' : ''} onClick={() => setLang('en')}>English</button>{' '}
          <button className={lang === 'es' ? 'on' : ''} onClick={() => setLang('es')}>Español</button>
        </div>
        <div className="eyebrow">{info.community}</div>
        {done ? (
          <div className="done">
            <div className="ic">{done === 'ok' ? '💛' : '🚶'}</div>
            <h1>{done === 'ok' ? t.thanksOk : done === 'needs_help' || done === 'escalated' ? t.thanksHelp : t.already}</h1>
            <p style={{ marginTop: 12 }}>{t.stay}</p>
          </div>
        ) : (
          <>
            <h1>{t.hi(info.member_first_name)}</h1>
            {info.summary ? <p>{info.summary}</p> : null}
            {info.actions?.length ? <ul>{info.actions.slice(0, 3).map((a, i) => <li key={i}>{a}</li>)}</ul> : null}
            <p><b>{t.q}</b></p>
            <button className="bigbtn ok" onClick={() => submit('ok')} disabled={!!choice}>{t.ok}</button>
            <button className="bigbtn help" onClick={() => submit('needs_help')} disabled={!!choice}>{t.help}</button>
            <textarea placeholder={t.note} value={note} onChange={(e) => setNote(e.target.value)} style={{ fontSize: 16 }} />
          </>
        )}
      </div>
    </div>
  );
}
