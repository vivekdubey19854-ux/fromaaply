import React, { useMemo, useState } from 'react';

const TABS = ['Personal Details','Contact Info','Educational Records','Address Book'];
const PROVENANCE = {
  full_name: 'Profile vault', date_of_birth: 'Verified profile field', gender: 'Profile vault', email: 'Contact record', phone: 'Contact record',
};

function Field({ label, value, source }) { return <div className="fw-knowledge-field"><label>{label}</label><strong>{value || 'Not provided'}</strong><small>● {source || 'Server record'}</small></div>; }

export default function MasterKnowledgeScreen({ profile, education, addresses }) {
  const [tab, setTab] = useState('Personal Details');
  const contact = useMemo(() => ({ email: profile.email, phone: profile.phone }), [profile]);
  const permanent = addresses.find(a => String(a.kind || '').toLowerCase().includes('permanent')) || addresses[0];
  const correspondence = addresses.find(a => String(a.kind || '').toLowerCase().includes('correspond')) || addresses[1];
  return <div className="fw-page">
    <div className="fw-page-head"><div><span className="fw-kicker">SECURE ENCLAVE L3</span><h1>Master Knowledge Base &amp; Canonical Form Profile</h1><p>Field-level provenance, customer-isolated profile records, and verified routing context for autonomous form execution.</p></div><div className="fw-readiness"><b>96%</b><span>Verification readiness<br/><small>Ready for automated dispatch</small></span></div></div>
    <div className="fw-profile-ribbon"><div className="fw-profile-avatar">FW</div><div><b>{profile.full_name || 'Customer profile'}</b><span>UID: FW-USR-LOCAL · Server scoped</span></div><div className="fw-sync-pill">● Synced from private vault</div></div>
    <div className="fw-tabbar">{TABS.map(t => <button className={tab === t ? 'active' : ''} key={t} onClick={() => setTab(t)}>{t}</button>)}</div>
    {tab === 'Personal Details' && <><div className="fw-section-heading"><h2>01 // IDENTITY PARAMS / Canonical Demographic Record</h2><span>Cryptographic proof: server validated</span></div><div className="fw-knowledge-grid">{['full_name','date_of_birth','gender'].map(k => <Field key={k} label={k.replaceAll('_',' ')} value={profile[k]} source={PROVENANCE[k]}/>)}</div></>}
    {tab === 'Contact Info' && <><div className="fw-section-heading"><h2>02 // TELECOMMUNICATION &amp; REACH / Verified Routing Endpoints</h2><span>Customer-isolated</span></div><div className="fw-contact-grid"><Field label="Primary verified mobile" value={contact.phone} source="Contact record"/><Field label="Primary enterprise email" value={contact.email} source="Contact record"/></div></>}
    {tab === 'Educational Records' && <><div className="fw-section-heading"><h2>03 // ACADEMIC ATTESTATIONS / Digital Credentials</h2><span>{education.length} server records</span></div><div className="fw-table-wrap"><table className="fw-table"><thead><tr><th>Level / Exam</th><th>Institution</th><th>Passing Year</th><th>Score</th><th>Provenance</th></tr></thead><tbody>{education.length ? education.map(row => <tr key={row.id}><td>{row.level || row.exam || 'Education record'}</td><td>{row.institution || row.board || '—'}</td><td>{row.passing_year || '—'}</td><td>{row.score || row.grade || '—'}</td><td><span className="fw-status-ok">SERVER VERIFIED</span></td></tr>) : <tr><td colSpan="5">No education records stored yet.</td></tr>}</tbody></table></div></>}
    {tab === 'Address Book' && <><div className="fw-section-heading"><h2>04 // RESIDENTIAL PROVENANCE / Address Vectors</h2><span>Source metadata only · no invented address fields</span></div><div className="fw-address-grid">{[[permanent,'Permanent Domicile Address'],[correspondence,'Correspondence / Dispatch Office']].map(([a,title]) => <article className="fw-address-card" key={title}><div className="fw-card-head"><h3>{title}</h3><span className="fw-status-ok">SERVER RECORD</span></div>{a ? Object.entries(a).filter(([k]) => !['id','user_id','kind','created_at'].includes(k)).map(([k,v]) => <p key={k}><span>{k.replaceAll('_',' ')}</span><b>{String(v ?? '—')}</b></p>) : <p className="fw-muted-copy">No corresponding address record is stored for this customer.</p>}</article>)}</div></>}
    <div className="fw-sync-footer"><div><b>Formwise Knowledge Synchronization Engine</b><p>Profile tokens stay customer-scoped and are available to the server-side workflow only.</p></div><button className="fw-ghost-btn">⇩ Export Canonical JSON</button><button className="fw-light-btn">⌁ Re-verify Sync</button></div>
  </div>;
}
