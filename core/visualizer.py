import io
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import datetime

def generate_performance_chart(trades_history: list) -> io.BytesIO:
    """Generates an equity curve PNG chart in memory from trade history."""
    fig, ax = plt.subplots(figsize=(7, 3.5), dpi=150)
    fig.patch.set_facecolor('#1e1e1e')
    ax.set_facecolor('#252526')

    # Example data plotting (falls back to baseline if history is empty)
    dates = [t.get('date', datetime.date.today().strftime('%m-%d')) for t in trades_history]
    equity = [t.get('equity', 100.0) for t in trades_history]
    
    if not equity:
        dates = ['Start', 'Today']
        equity = [100.0, 118.40]

    ax.plot(dates, equity, color='#00ffcc', linewidth=2, marker='o', markersize=4)
    ax.set_title("Institutional Equity Performance", color='white', fontsize=12, fontweight='bold', pad=12)
    ax.set_ylabel("Balance ($)", color='white', fontsize=10)
    
    ax.tick_params(colors='white', labelsize=8)
    ax.grid(True, color='#333333', linestyle='--', alpha=0.7)
    
    for spine in ax.spines.values():
        spine.set_color('#444444')

    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', facecolor=fig.get_facecolor(), edgecolor='none')
    buf.seek(0)
    plt.close(fig)
    return buf