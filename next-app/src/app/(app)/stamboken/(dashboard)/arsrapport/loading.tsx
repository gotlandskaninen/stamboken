import styles from "./arsrapport.module.css";

export default function ArsrapportLoading() {
  return (
    <div className={styles.root} aria-busy="true">
      <h1 className={styles.title}>Årsrapport</h1>
      {[0, 1, 2].map((i) => (
        <div key={i} className={styles.skeleton} />
      ))}
    </div>
  );
}
