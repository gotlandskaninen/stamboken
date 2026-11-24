import styles from "../../arsrapport.module.css";

export default function StatusLoading() {
  return (
    <div className={styles.root} aria-busy="true">
      <h1 className={styles.title}>Status</h1>
      {[0, 1, 2, 3, 4].map((i) => (
        <div key={i} className={styles.skeleton} />
      ))}
    </div>
  );
}
